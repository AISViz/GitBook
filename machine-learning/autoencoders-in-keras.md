---
description: >-
  A GRU autoencoder in Keras that compresses four hours of vessel track and
  decodes an eight-hour forecast, trained with probabilistic teacher forcing.
icon: k
---

# AutoEncoders in Keras

This tutorial builds a GRU autoencoder in Keras that reads four hours of a vessel's AIS track and forecasts the next eight hours of movement. Training uses probabilistic teacher forcing, feeding the decoder a mix of ground truth and its own predictions so convergence is faster and long-horizon forecasts stay stable. You walk away able to window raw AIS into supervised sequence pairs and train a sequence-to-sequence forecaster with a loss that thinks in meters.

## What you will learn

* Querying, segmenting, and interpolating a year of AIS tracks with AISdb
* Windowing trajectories into fixed input and output sequences with delta features
* Building a GRU encoder-decoder with a probabilistic teacher-forcing layer in Keras
* Training with a haversine-based custom loss and standard Keras callbacks
* Evaluating forecasts as physical distance errors on held-out vessels

## Prerequisites

```bash
pip install aisdb tensorflow geopandas shapely plotly wandb scikit-learn tqdm
```

The run shown on this page queried a private regional AISdb database covering Atlantic Canada, `ais-atlantic-canada.db`, built from a full year of decoded AIS traffic (2021-01-01 through 2021-12-31), because forecasting eight hours from four needs enough long, clean voyages to fill the training buckets built below. If you do not have a private database, decode the open NOAA day file ([AIS\_2020\_01\_01.zip](https://coast.noaa.gov/htdata/CMSP/AISDataHandler/2020/AIS_2020_01_01.zip)) into SQLite as shown in [Using Your AIS Data](../tutorials/using-your-ais-data.md), point `get_tracks(dbname, "01012020", "02012020")` at it, and add `xmin=-98, xmax=-80, ymin=24, ymax=31` to the `DBQuery` call inside `qry_database`. One day of AIS exercises the full pipeline end to end but yields far fewer usable trajectories and a weaker fit than the full-year run shown here. You also need the Natural Earth 50m land shapefile (`ne_50m_land.shp`) under `shapes/`, a free Weights & Biases account for training logs, and a notebook environment, since the evaluation renders interactive Plotly figures.

## Step 1. Set up imports and working folders

Everything downstream assumes these imports, a fixed random seed, and four working folders for the database, shapefiles, cached datasets, and model weights.

```python
import os
import random
import pickle as pkl
import multiprocessing
from multiprocessing import Pool
from functools import partial
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import numpy as np
import geopandas as gpd
from shapely.geometry import Point
from tqdm import tqdm
from IPython.display import display
import plotly.graph_objects as go

import aisdb

import tensorflow as tf
from tensorflow.keras import backend as K
from tensorflow.keras.layers import Layer, Input, GRU, LSTM, RepeatVector, TimeDistributed, Dense
from tensorflow.keras.models import Model
from tensorflow.keras.optimizers import AdamW
from tensorflow.keras.callbacks import ReduceLROnPlateau, EarlyStopping

import wandb
from sklearn.metrics import (
    r2_score, mean_squared_error, mean_absolute_error,
    explained_variance_score, mean_absolute_percentage_error)

seed_value = 42
random.seed(seed_value)
np.random.seed(seed_value)
tf.random.set_seed(seed_value)

ROOT = os.getcwd()
PATH = "data"      # holds the SQLite database
SHAPES = "shapes"  # holds the Natural Earth land shapefile
ESRF = "cache"     # holds intermediate pickled datasets
MODELS = "models"  # holds trained weights and training histories
for folder in (PATH, SHAPES, ESRF, MODELS):
    os.makedirs(os.path.join(ROOT, folder), exist_ok=True)
```

## Step 2. Query and segment a year of AIS

AISdb pulls the raw messages, splits tracks on 24-hour silences, drops speed and distance outliers, and interpolates every position to a fixed 5-minute cadence, which the windowing below depends on. A vessel can appear in several disjoint tracks after splitting, so `voyages` groups the segments by MMSI.

```python
def qry_database(dbname, start_time, stop_time):
    d_threshold = 200000  # max distance (in meters) between two messages of a track
    s_threshold = 50  # max speed (in knots) between two AIS messages of a track
    t_threshold = timedelta(hours=24)  # max time between messages of a track
    try:
        with aisdb.DBConn(dbpath=os.path.join(ROOT, PATH, dbname)) as dbconn:
            tracks = aisdb.TrackGen(
                aisdb.DBQuery(
                    dbconn=dbconn,
                    callback=aisdb.database.sqlfcn_callbacks.in_timerange,
                    start=start_time, end=stop_time).gen_qry(),
                    decimate=False)  # trajectory compression
            tracks = aisdb.split_timedelta(tracks, t_threshold)
            tracks = aisdb.encode_greatcircledistance(tracks, distance_threshold=d_threshold, speed_threshold=s_threshold)
            tracks = aisdb.interp_time(tracks, step=timedelta(minutes=5))
            return list(tracks)  # list of segmented pre-processed tracks
    except SyntaxError as e: return []  # no results for query

def get_tracks(dbname, start_ddmmyyyy, stop_ddmmyyyy):
    stop_time = datetime.strptime(stop_ddmmyyyy, "%d%m%Y")
    start_time = datetime.strptime(start_ddmmyyyy, "%d%m%Y")
    return qry_database(dbname, start_time, stop_time)

tracks = get_tracks("ais-atlantic-canada.db", "01012021", "31122021")

voyages = defaultdict(list)
for track in tracks:
    voyages[track["mmsi"]].append(track)
voyages = dict(voyages)
```

The dataset covers the Atlantic Canada receiver network, roughly a 100 km radius around each station.

<figure><img src="../.gitbook/assets/image (14).png" alt=""><figcaption><p>100 km AIS receiver coverage over Atlantic Canada, from the private regional database used in this tutorial (full year 2021).</p></figcaption></figure>

## Step 3. Drop tracks that touch land

Interpolation and decoding glitches can place positions inland, and a forecaster trained on impossible tracks learns impossible motion. Any track with a single point on land is removed, in parallel across MMSIs, and the curated result is cached to disk so the filter runs once.

```python
land_polygons = gpd.read_file(os.path.join(ROOT, SHAPES, "ne_50m_land.shp"))

def is_on_land(lat, lon, land_polygons):
    return land_polygons.contains(Point(lon, lat)).any()

def is_track_on_land(track, land_polygons):
    for lat, lon in zip(track["lat"], track["lon"]):
        if is_on_land(lat, lon, land_polygons):
            return True
    return False

def process_mmsi(item, polygons):
    mmsi, tracks = item
    filtered_tracks = [t for t in tracks if not is_track_on_land(t, polygons)]
    return mmsi, filtered_tracks, len(tracks)

def process_voyages(voyages, land_polygons):

    def process_mmsi_callback(result, progress_bar):
        mmsi, filtered_tracks, _ = result
        voyages[mmsi] = filtered_tracks
        progress_bar.update(1)

    progress_bar = tqdm(total=len(voyages), desc="MMSIs processed")
    with ThreadPoolExecutor(max_workers=multiprocessing.cpu_count()) as executor:
        futures = {executor.submit(process_mmsi, item, land_polygons): item for item in voyages.items()}
        for future in as_completed(futures):
            process_mmsi_callback(future.result(), progress_bar)
    progress_bar.close()
    return voyages

file_name = "curated-ais.pkl"
full_path = os.path.join(ROOT, ESRF, file_name)
if not os.path.exists(full_path):
    voyages = process_voyages(voyages, land_polygons)
    pkl.dump(voyages, open(full_path, "wb"))
else: voyages = pkl.load(open(full_path, "rb"))

voyages_counts = {k: len(voyages[k]) for k in voyages.keys()}
```

## Step 4. Split voyages into train and test

Most MMSIs have between 1 and 49 segments while a few reach 176, so a naive split would let segment-rich vessels dominate. Categorizing voyages as long-term (30 or more segments) or short-term and splitting each bucket 80/20 keeps both behaviors represented in both sets.

```python
long_term_voyages, short_term_voyages = [], []
for k in voyages_counts:
    if voyages_counts[k] < 30:
        short_term_voyages.append(k)
    else: long_term_voyages.append(k)

random.shuffle(short_term_voyages)
random.shuffle(long_term_voyages)

train_voyage, test_voyage = {}, {}
for i, k in enumerate(short_term_voyages):
    if i < int(0.8 * len(short_term_voyages)):
        train_voyage[k] = voyages[k]
    else: test_voyage[k] = voyages[k]
for i, k in enumerate(long_term_voyages):
    if i < int(0.8 * len(long_term_voyages)):
        train_voyage[k] = voyages[k]
    else: test_voyage[k] = voyages[k]
```

## Step 5. Window trajectories into samples

The model takes 4 hours of input (48 steps at the 5-minute cadence) and predicts 8 hours (96 steps), so every voyage shorter than 144 steps is dropped and the rest gain delta features that expose the rate of change. A window then slides one step at a time along each voyage, producing overlapping input/output pairs, and each input window gets a straightness score (straight-line over along-track haversine distance, inverted and scaled) so complex, twisty samples can be weighted more heavily during training.

```python
INPUT_TIMESTEPS = 48   # 4 hours * 12 AIS messages/h
INPUT_VARIABLES = 4    # Longitude, Latitude, COG, and SOG
OUTPUT_TIMESTEPS = 96  # 8 hours * 12 AIS messages/h
OUTPUT_VARIABLES = 2   # Longitude and Latitude
NUM_WORKERS = multiprocessing.cpu_count()
INPUT_VARIABLES *= 2   # double the features with deltas

def filter_and_transform_voyages(voyages):
    filtered_voyages = {}
    for k, v in voyages.items():
        voyages_track = []
        for voyage in v:
            if len(voyage["time"]) > (INPUT_TIMESTEPS + OUTPUT_TIMESTEPS):
                mtx = np.vstack([voyage["lon"], voyage["lat"],
                                 voyage["cog"], voyage["sog"]]).T
                deltas = np.diff(mtx, axis=0)
                deltas = np.vstack([np.zeros(deltas.shape[1]), deltas])
                mtx = np.hstack([mtx, deltas])
                voyages_track.append(mtx)
        if len(voyages_track) > 0:
            filtered_voyages[k] = voyages_track
    return filtered_voyages

train_voyage = filter_and_transform_voyages(train_voyage)
test_voyage = filter_and_transform_voyages(test_voyage)
```

```python
def haversine_distance(lon_1, lat_1, lon_2, lat_2):
    lon_1, lat_1, lon_2, lat_2 = map(np.radians, [lon_1, lat_1, lon_2, lat_2])
    a = np.sin((lat_2 - lat_1) / 2) ** 2 + np.cos(lat_1) * np.cos(lat_2) * np.sin((lon_2 - lon_1) / 2) ** 2
    return (2 * np.arcsin(np.sqrt(a))) * 6371000  # R: 6,371,000 meters

def trajectory_straightness(x):
    start_point, end_point = x[0, :2], x[-1, :2]
    x_coordinates, y_coordinates = x[:-1, 0], x[:-1, 1]
    x_coordinates_next, y_coordinates_next = x[1:, 0], x[1:, 1]
    consecutive_distances = np.array(haversine_distance(x_coordinates, y_coordinates, x_coordinates_next, y_coordinates_next))
    straight_line_distance = np.array(haversine_distance(start_point[0], start_point[1], end_point[0], end_point[1]))
    result = straight_line_distance / np.sum(consecutive_distances)
    return result if not np.isnan(result) else 1

def process_voyage(voyage, mmsi, max_size, overlap_size=1):
    straightness_ratios, mmsis, x, y = [], [], [], []
    for j in range(0, voyage.shape[0] - max_size, 1):
        x_sample = voyage[(0 + j):(INPUT_TIMESTEPS + j)]
        y_sample = voyage[(INPUT_TIMESTEPS + j - overlap_size):(max_size + j), 0:OUTPUT_VARIABLES]
        straightness = trajectory_straightness(x_sample)
        straightness_ratios.append(straightness)
        x.append(x_sample.T)
        y.append(y_sample.T)
        mmsis.append(mmsi)
    return straightness_ratios, mmsis, x, y

def process_data(voyages):
    max_size = INPUT_TIMESTEPS + OUTPUT_TIMESTEPS

    def process_voyage_callback(result, pbar):
        pbar.update(1)
        return result

    with Pool(NUM_WORKERS) as pool, tqdm(total=sum(len(v) for v in voyages.values()), desc="Voyages") as pbar:
        results = []
        for mmsi in voyages:
            for voyage in voyages[mmsi]:
                callback = partial(process_voyage_callback, pbar=pbar)
                results.append(pool.apply_async(process_voyage, (voyage, mmsi, max_size), callback=callback))
        pool.close()
        pool.join()

        straightness_ratios, mmsis, x, y = [], [], [], []
        for result in results:
            s_ratios, s_mmsis, s_x, s_y = result.get()
            straightness_ratios.extend(s_ratios)
            mmsis.extend(s_mmsis)
            x.extend(s_x)
            y.extend(s_y)

    x, y = np.stack(x), np.stack(y)
    x, y = np.transpose(x, (0, 2, 1)), np.transpose(y, (0, 2, 1))
    straightness_ratios = np.array(straightness_ratios)
    min_straightness, max_straightness = np.min(straightness_ratios), np.max(straightness_ratios)
    scaled_straightness_ratios = (straightness_ratios - min_straightness) / (max_straightness - min_straightness)
    scaled_straightness_ratios = 1. - scaled_straightness_ratios

    print(f"Final number of samples = {len(x)}", end="\n\n")
    return mmsis, x, y, scaled_straightness_ratios

mmsi_train, x_train, y_train, straightness_ratios = process_data(train_voyage)
mmsi_test, x_test, y_test, _ = process_data(test_voyage)
```

## Step 6. Normalize the samples

Three chained transforms bring every feature onto a comparable scale. Longitude, latitude, COG, and SOG first map to \[0, 1] with domain bounds for Atlantic Canada, then standardization centers the data to fight vanishing gradients, and a final zero-one pass matches the range the activations expect. `denormalize_x` reverses the chain when plotting inputs later.

```python
def normalize_dataset(x_train, x_test, y_train,
                      lat_min=42, lat_max=52, lon_min=-70, lon_max=-50, max_sog=50):

    def normalize(arr, min_val, max_val):
        return (arr - min_val) / (max_val - min_val)

    # Initial normalization
    x_train[:, :, :2] = normalize(x_train[:, :, :2], np.array([lon_min, lat_min]), np.array([lon_max, lat_max]))
    y_train[:, :, :2] = normalize(y_train[:, :, :2], np.array([lon_min, lat_min]), np.array([lon_max, lat_max]))
    x_test[:, :, :2] = normalize(x_test[:, :, :2], np.array([lon_min, lat_min]), np.array([lon_max, lat_max]))

    x_train[:, :, 2:4] = x_train[:, :, 2:4] / np.array([360, max_sog])
    x_test[:, :, 2:4] = x_test[:, :, 2:4] / np.array([360, max_sog])

    # Standardize X and Y
    x_mean, x_std = np.mean(x_train, axis=(0, 1)), np.std(x_train, axis=(0, 1))
    y_mean, y_std = np.mean(y_train, axis=(0, 1)), np.std(y_train, axis=(0, 1))

    x_train = (x_train - x_mean) / x_std
    y_train = (y_train - y_mean) / y_std
    x_test = (x_test - x_mean) / x_std

    # Final zero-one normalization
    x_min, x_max = np.min(x_train, axis=(0, 1)), np.max(x_train, axis=(0, 1))
    y_min, y_max = np.min(y_train, axis=(0, 1)), np.max(y_train, axis=(0, 1))

    x_train = (x_train - x_min) / (x_max - x_min)
    y_train = (y_train - y_min) / (y_max - y_min)
    x_test = (x_test - x_min) / (x_max - x_min)

    return x_train, x_test, y_train, y_mean, y_std, y_min, y_max, x_mean, x_std, x_min, x_max

x_train, x_test, y_train, y_mean, y_std, y_min, y_max, x_mean, x_std, x_min, x_max = normalize_dataset(x_train, x_test, y_train)

def denormalize_x(x_data, x_mean, x_std, x_min, x_max,
                  lat_min=42, lat_max=52, lon_min=-70, lon_max=-50):
    x_data = x_data * (x_max - x_min) + x_min  # reverse zero-one normalization
    x_data = x_data * x_std + x_mean  # reverse standardization
    x_data[:, :, 0] = x_data[:, :, 0] * (lon_max - lon_min) + lon_min
    x_data[:, :, 1] = x_data[:, :, 1] * (lat_max - lat_min) + lat_min
    return x_data
```

## Step 7. Build the teacher-forcing GRU autoencoder

A GRU autoencoder compresses the input sequence into a single hidden state and decodes it into the forecast, and a GRU (Cho et al., 2014, [arXiv:1406.1078](https://arxiv.org/abs/1406.1078)) handles the temporal dependencies in each direction. The twist is the `ProbabilisticTeacherForcing` layer, which at every decoder step randomly feeds either the ground-truth previous position or the model's own previous output, governed by a mixing probability. Two graphs share the same trained layers, a training model that takes the ground-truth decoder input and a clean inference model that runs from the encoder alone.

```python
tf.keras.backend.clear_session()
_ = wandb.login(force=True)

class ProbabilisticTeacherForcing(Layer):
    def __init__(self, **kwargs):
        super(ProbabilisticTeacherForcing, self).__init__(**kwargs)

    def call(self, inputs):
        decoder_gt_input, decoder_output, mixing_prob = inputs
        mixing_prob = tf.expand_dims(mixing_prob, axis=-1)  # add a dimension for broadcasting
        mixing_prob = tf.broadcast_to(mixing_prob, tf.shape(decoder_gt_input))
        return tf.where(tf.random.uniform(tf.shape(decoder_gt_input)) < mixing_prob, decoder_gt_input, decoder_output)

def build_model(rnn_unit="GRU", hidden_size=64):
    encoder_input = Input(shape=(INPUT_TIMESTEPS, INPUT_VARIABLES), name="Encoder_Input")
    decoder_gt_input = Input(shape=((OUTPUT_TIMESTEPS - 1), OUTPUT_VARIABLES), name="Decoder-GT-Input")
    mixing_prob_input = Input(shape=(1,), name="Mixing_Probability")

    # Encoder
    encoder_gru = eval(rnn_unit)(hidden_size, activation="relu", name="Encoder")(encoder_input)
    repeat_vector = RepeatVector((OUTPUT_TIMESTEPS - 1), name="Repeater")(encoder_gru)

    # Inference Decoder
    decoder_gru = eval(rnn_unit)(hidden_size, activation="relu", return_sequences=True, name="Decoder")
    decoder_output = decoder_gru(repeat_vector, initial_state=encoder_gru)

    # Adjust decoder_output shape
    dense_output_adjust = TimeDistributed(Dense(OUTPUT_VARIABLES), name="Output_Adjust")
    adjusted_decoder_output = dense_output_adjust(decoder_output)

    # Training Decoder
    decoder_gru_tf = eval(rnn_unit)(hidden_size, activation="relu", return_sequences=True, name="Decoder-TF")
    probabilistic_tf_layer = ProbabilisticTeacherForcing(name="Probabilistic_Teacher_Forcing")
    mixed_input = probabilistic_tf_layer([decoder_gt_input, adjusted_decoder_output, mixing_prob_input])
    tf_output = decoder_gru_tf(mixed_input, initial_state=encoder_gru)
    tf_output = dense_output_adjust(tf_output)

    training_model = Model(inputs=[encoder_input, decoder_gt_input, mixing_prob_input], outputs=tf_output, name="Training")
    inference_model = Model(inputs=encoder_input, outputs=adjusted_decoder_output, name="Inference")

    return training_model, inference_model

training_model, model = build_model()
```

## Step 8. Compile with a haversine loss

Losses on normalized coordinates hide the physical size of an error, so the custom loss denormalizes both tensors back to degrees and works in meters through a TensorFlow haversine. It also computes step-to-step distance consistency and an input-to-output continuity penalty, available in the commented weighted combination, while the run shown trained on the RMSE term alone.

```python
def denormalize_y(y_data, y_mean, y_std, y_min, y_max, lat_min=42, lat_max=52, lon_min=-70, lon_max=-50):
    scales = tf.constant([lon_max - lon_min, lat_max - lat_min], dtype=tf.float32)
    biases = tf.constant([lon_min, lat_min], dtype=tf.float32)
    y_data = y_data * (y_max - y_min) + y_min  # reverse zero-one normalization
    y_data = y_data * y_std + y_mean  # reverse standardization
    return y_data * scales + biases  # reverse initial normalization

def haversine_distance(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = [tf.math.multiply(x, tf.divide(tf.constant(np.pi), 180.)) for x in [lon1, lat1, lon2, lat2]]
    a = tf.math.square(tf.math.sin((lat2 - lat1) / 2.)) + tf.math.cos(lat1) * tf.math.cos(lat2) * tf.math.square(tf.math.sin((lon2 - lon1) / 2.))
    return 2 * 6371000 * tf.math.asin(tf.math.sqrt(a))  # The earth radius is 6,371,000 meters

def custom_loss(y_true, y_pred):
    tf.debugging.check_numerics(y_true, "y_true contains NaNs")
    tf.debugging.check_numerics(y_pred, "y_pred contains NaNs")

    # Denormalize true and predicted y
    y_true_denorm = denormalize_y(y_true, y_mean, y_std, y_min, y_max)
    y_pred_denorm = denormalize_y(y_pred, y_mean, y_std, y_min, y_max)

    # Haversine distance between consecutive true and predicted positions
    true_dist = haversine_distance(y_true_denorm[:, 1:, 0], y_true_denorm[:, 1:, 1], y_true_denorm[:, :-1, 0], y_true_denorm[:, :-1, 1])
    pred_dist = haversine_distance(y_pred_denorm[:, 1:, 0], y_pred_denorm[:, 1:, 1], y_pred_denorm[:, :-1, 0], y_pred_denorm[:, :-1, 1])

    # Convert maximum speed from knots to meters per 5 minutes
    max_speed_m_per_5min = 50 * 1.852 * 1000 * 5 / 60

    # Penalize predicted step distances beyond the maximum possible distance
    dist_diff = tf.abs(true_dist - pred_dist)
    dist_diff = tf.where(pred_dist > max_speed_m_per_5min, pred_dist - max_speed_m_per_5min, dist_diff)

    # Penalty for the first output coordinate not matching the last input
    input_output_diff = haversine_distance(y_true_denorm[:, 0, 0], y_true_denorm[:, 0, 1], y_pred_denorm[:, 0, 0], y_pred_denorm[:, 0, 1])

    # RMSE excluding the first element
    rmse = K.sqrt(K.mean(K.square(y_true_denorm[:, 1:, :] - y_pred_denorm[:, 1:, :]), axis=1))

    # return 0.25 * K.mean(input_output_diff) + 0.35 * K.mean(dist_diff) + 0.40 * K.mean(rmse)
    return K.mean(rmse)

def compile_model(model, learning_rate, clipnorm, jit_compile, skip_summary=False):
    optimizer = AdamW(learning_rate=learning_rate, clipnorm=clipnorm, jit_compile=jit_compile)
    model.compile(optimizer=optimizer, loss=custom_loss, metrics=["mae", "mape"], weighted_metrics=[], jit_compile=jit_compile)
    if not skip_summary: model.summary()

compile_model(training_model, learning_rate=0.001, clipnorm=1, jit_compile=True)
compile_model(model, learning_rate=0.001, clipnorm=1, jit_compile=True)
```

<details>

<summary>Model summary output (Training graph and Inference graph, full layer listing)</summary>

```brightscript
Model: "Training"
__________________________________________________________________________________________________
 Layer (type)                   Output Shape         Param #     Connected to                     
==================================================================================================
 Encoder_Input (InputLayer)     [(None, 48, 8)]      0           []                               
                                                                                                  
 Encoder (GRU)                  (None, 64)           14208       ['Encoder_Input[0][0]']          
                                                                                                  
 Repeater (RepeatVector)        (None, 95, 64)       0           ['Encoder[0][0]']                
                                                                                                  
 Decoder (GRU)                  (None, 95, 64)       24960       ['Repeater[0][0]',               
                                                                  'Encoder[0][0]']                
                                                                                                  
 Output_Adjust (TimeDistributed  (None, 95, 2)       130         ['Decoder[0][0]',                
 )                                                                'Decoder-TF[0][0]']             
                                                                                                  
 Decoder-GT-Input (InputLayer)  [(None, 95, 2)]      0           []                               
                                                                                                  
 Mixing_Probability (InputLayer  [(None, 1)]         0           []                               
 )                                                                                                
                                                                                                  
 Probabilistic_Teacher_Forcing   (None, 95, 2)       0           ['Decoder-GT-Input[0][0]',       
 (ProbabilisticTeacherForcing)                                    'Output_Adjust[0][0]',          
                                                                  'Mixing_Probability[0][0]']     
                                                                                                  
 Decoder-TF (GRU)               (None, 95, 64)       13056       ['Probabilistic_Teacher_Forcing[0
                                                                 ][0]',                           
                                                                  'Encoder[0][0]']                
                                                                                                  
==================================================================================================
Total params: 52,354
Trainable params: 52,354
Non-trainable params: 0
__________________________________________________________________________________________________
Model: "Inference"
__________________________________________________________________________________________________
 Layer (type)                   Output Shape         Param #     Connected to                     
==================================================================================================
 Encoder_Input (InputLayer)     [(None, 48, 8)]      0           []                               
                                                                                                  
 Encoder (GRU)                  (None, 64)           14208       ['Encoder_Input[0][0]']          
                                                                                                  
 Repeater (RepeatVector)        (None, 95, 64)       0           ['Encoder[0][0]']                
                                                                                                  
 Decoder (GRU)                  (None, 95, 64)       24960       ['Repeater[0][0]',               
                                                                  'Encoder[0][0]']                
                                                                                                  
 Output_Adjust (TimeDistributed  (None, 95, 2)       130         ['Decoder[0][0]']                
 )                                                                                                
                                                                                                  
==================================================================================================
Total params: 39,298
Trainable params: 39,298
Non-trainable params: 0
__________________________________________________________________________________________________
```

</details>

## Step 9. Train with callbacks

Training pads the decoder's ground-truth input with a leading zero step, fixes the mixing probability at 0.5, and lets the callbacks manage the rest, with `ReduceLROnPlateau` lowering the learning rate when validation stalls, `EarlyStopping` restoring the best weights, `ModelCheckpoint` saving them, and `WandbMetricsLogger` streaming metrics to Weights & Biases (pass `skip_wandb=True` to drop it). The straightness weights from Step 5 plug in through the commented `sample_weight` argument, unused in the run shown.

```python
def create_callbacks(model_name, monitor="val_loss", factor=0.2, lr_patience=3, ep_patience=12, min_lr=0, verbose=0, restore_best_weights=True, skip_wandb=False):
    return  ([wandb.keras.WandbMetricsLogger()] if not skip_wandb else []) + [
            ReduceLROnPlateau(monitor=monitor, factor=factor, patience=lr_patience, min_lr=min_lr, verbose=verbose),
            EarlyStopping(monitor=monitor, patience=ep_patience, verbose=verbose, restore_best_weights=restore_best_weights),
            tf.keras.callbacks.ModelCheckpoint(os.path.join(ROOT, MODELS, model_name), monitor="val_loss", mode="min", save_best_only=True, verbose=verbose)]

def train_model(model, x_train, y_train, batch_size, epochs, validation_split, model_name):
    run = wandb.init(project="kAISdb", anonymous="allow")

    mixing_prob = 0.5  # probability of feeding the decoder ground truth

    # Match y_train to the decoder output length
    y_train = y_train[:, :(OUTPUT_TIMESTEPS - 1), :]

    # Ground-truth decoder input, padded with a zero step at the front
    decoder_ground_truth_input_data = (np.zeros((y_train.shape[0], 1, y_train.shape[2])), y_train[:, :-1, :])
    decoder_ground_truth_input_data = np.concatenate(decoder_ground_truth_input_data, axis=1)

    try:
        with tf.device(tf.test.gpu_device_name()):
            training_model.fit([x_train, decoder_ground_truth_input_data, np.full((x_train.shape[0], 1), mixing_prob)], y_train, batch_size=batch_size, epochs=epochs,
                            verbose=2, validation_split=validation_split, callbacks=create_callbacks(model_name))
            # , sample_weight=straightness_ratios)
    except KeyboardInterrupt as e:
        print("\nRestoring best weights [...]")
        training_model.load_weights(model_name)
        for layer in model.layers:  # transfer weights to the inference model
            if layer.name in [l.name for l in training_model.layers]:
                layer.set_weights(training_model.get_layer(layer.name).get_weights())

    run.finish()

model_name = "TF-GRU-AE.h5"
train_model(model, x_train, y_train, batch_size=1024,
            epochs=250, validation_split=0.2,
            model_name=model_name)
```

## Step 10. Evaluate in meters

The evaluation predicts the held-out set once, denormalizes everything back to real coordinates, plots sample forecasts against the ground truth, and reports distance errors through the haversine plus standard regression metrics. The slicing with `[:, 1:]` aligns the 96-step targets with the 95-step teacher-forced outputs.

```python
def evaluate_model(model, x_test, y_test, y_mean, y_std, y_min, y_max, y_pred=None):

    def single_trajectory_error(y_test, y_pred, index):
        distances = haversine_distance(y_test[index, :, 0], y_test[index, :, 1], y_pred[index, :, 0], y_pred[index, :, 1])
        return np.min(distances), np.max(distances), np.mean(distances), np.median(distances)

    def all_trajectory_error(y_test, y_pred):
        errors = [single_trajectory_error(y_test[:, 1:], y_pred, i) for i in range(y_test.shape[0])]
        min_errors, max_errors, mean_errors, median_errors = zip(*errors)
        return min(min_errors), max(max_errors), np.mean(mean_errors), np.median(median_errors)

    def plot_trajectory(x_test, y_test, y_pred, sample_index):
        min_error, max_error, mean_error, median_error = single_trajectory_error(y_test, y_pred, sample_index)
        fig = go.Figure()

        fig.add_trace(go.Scatter(x=x_test[sample_index, :, 0], y=x_test[sample_index, :, 1], mode="lines", name="Input Data", line=dict(color="green")))
        fig.add_trace(go.Scatter(x=y_test[sample_index, :, 0], y=y_test[sample_index, :, 1], mode="lines", name="Ground Truth", line=dict(color="blue")))
        fig.add_trace(go.Scatter(x=y_pred[sample_index, :, 0], y=y_pred[sample_index, :, 1], mode="lines", name="Forecasted Trajectory", line=dict(color="red")))

        fig.update_layout(title=f"Sample Index: {sample_index} | Distance Errors (in meters):<br>Min: {min_error:.2f}m, Max: {max_error:.2f}m, "
                                f"Mean: {mean_error:.2f}m, Median: {median_error:.2f}m", xaxis_title="Longitude", yaxis_title="Latitude",
                          plot_bgcolor="#e4eaf0", paper_bgcolor="#fcfcfc", width=700, height=600)

        max_lon, max_lat = -58.705587131108196, 47.89066160591873
        min_lon, min_lat = -61.34247286889181, 46.09201839408127

        fig.update_xaxes(range=[min_lon, max_lon])
        fig.update_yaxes(range=[min_lat, max_lat])

        return fig

    if y_pred is None:
        with tf.device(tf.test.gpu_device_name()):
            y_pred = model.predict(x_test, verbose=0)
    y_pred_o = y_pred  # preserve the result

    x_test = denormalize_x(x_test, x_mean, x_std, x_min, x_max)
    y_pred = denormalize_y(y_pred_o, y_mean, y_std, y_min, y_max)

    for sample_index in [1000, 2500, 5000, 7500]:
        display(plot_trajectory(x_test, y_test[:, 1:], y_pred, sample_index))

    # The metrics require a lower dimension (no impact on the results)
    y_test_reshaped = np.reshape(y_test[:, 1:], (-1, y_test.shape[2]))
    y_pred_reshaped = np.reshape(y_pred, (-1, y_pred.shape[2]))

    # Physical distance error given in meters
    all_min_error, all_max_error, all_mean_error, all_median_error = all_trajectory_error(y_test, y_pred)

    print("\nAll Trajectories Min DE: {:.4f}m".format(all_min_error))
    print("All Trajectories Max DE: {:.4f}m".format(all_max_error))
    print("All Trajectories Mean DE: {:.4f}m".format(all_mean_error))
    print("All Trajectories Median DE: {:.4f}m".format(all_median_error))

    r2 = r2_score(y_test_reshaped, y_pred_reshaped)
    mse = mean_squared_error(y_test_reshaped, y_pred_reshaped)
    mae = mean_absolute_error(y_test_reshaped, y_pred_reshaped)
    evs = explained_variance_score(y_test_reshaped, y_pred_reshaped)
    mape = mean_absolute_percentage_error(y_test_reshaped, y_pred_reshaped)
    rmse = np.sqrt(mse)

    print(f"\nTest R^2: {r2:.4f}")
    print(f"Test MAE: {mae:.4f}")
    print(f"Test MSE: {mse:.4f}")
    print(f"Test RMSE: {rmse:.4f}")
    print(f"Test MAPE: {mape:.4f}")
    print(f"Test Explained Variance Score: {evs:.4f}")

    return y_pred_o

_ = evaluate_model(model, x_test, y_test, y_mean, y_std, y_min, y_max)
```

## Results

Each of the four plotted samples shows the green input track, the blue ground truth, and the red forecast, with per-trajectory min, max, mean, and median distance errors in the title. The console output then aggregates those distance errors across every test trajectory and adds R squared, MAE, MSE, RMSE, MAPE, and explained variance over all predicted coordinates. Absolute numbers depend on the database behind the run, the vessel mix, and the region, so compare the mean and median distance errors of your own runs before and after a change rather than chasing a universal benchmark, and expect visibly weaker forecasts from the one-day NOAA drop-in than from a full-year regional database.

## Takeaway

* Probabilistic teacher forcing trains the decoder on a mix of ground truth and its own predictions, speeding convergence while keeping the inference graph free of ground-truth inputs, and the two graphs share weights by sharing layers.
* A loss that denormalizes to meters through the haversine judges forecasts in physical units, and extra terms for speed-consistency and continuity are wired in when plain RMSE is not enough.
* Windowing with deltas, land filtering, and a length-balanced 80/20 split matter as much as the architecture, since a forecaster learns whatever the samples contain.
* From here, tune the layer widths and the mixing probability with a search library such as HyperOpt, and probe the trained model with permutation feature importance or UMAP projections of its latent space.

Next, [Embedding with traj2vec](embedding-with-traj2vec.md) learns a fixed-length representation of an entire voyage instead of stepping through it one position at a time.
