---
description: >-
  Discretize AIS trajectories onto an H3 grid and train a t2vec-style
  encoder-decoder in PyTorch that embeds vessel tracks as fixed-length vectors.
icon: chart-scatter-3d
---

# Embedding with traj2vec

Inspired by word2vec, traj2vec treats a vessel trajectory the way a language model treats a sentence. This tutorial discretizes raw AIS tracks onto an H3 hexagon grid so each trajectory becomes a sequence of spatial tokens, then trains a PyTorch encoder-decoder to predict the next cell, which yields a fixed-length embedding for every track as a byproduct. Trajectories that look alike end up close together in embedding space, ready for clustering, similarity search, or anomaly detection downstream.

## What you will learn

* Cleaning, segmenting, and interpolating raw AIS tracks with AISdb
* Tokenizing trajectories into H3 cell sequences and building a vocabulary with special tokens
* Writing NLP-style `.src`/`.trg` datasets with a train/validation/test split
* Training a t2vec encoder-decoder with generative and triplet losses
* Reading perplexity as a sanity check on next-cell prediction

## Prerequisites

```bash
pip install aisdb torch h3 geopandas cartopy matplotlib seaborn scikit-learn tqdm nest_asyncio
```

The run captured on this page pulls a month of Gulf of St. Lawrence and Nova Scotia coastal traffic (January 2023) from a private PostgreSQL database, so the figures and metrics below are not reproducible without it. The pipeline itself runs against any AISdb database. For open data, download the NOAA day file for 2020-01-01 from [coast.noaa.gov](https://coast.noaa.gov/htdata/CMSP/AISDataHandler/2020/AIS_2020_01_01.zip), decode the unzipped CSV with `decode_msgs(..., source='NOAA')` into a `SQLiteDBConn`, swap that connection for the `PostgresDBConn` below, and query the Gulf of Mexico window (`xmin=-98, xmax=-80, ymin=24, ymax=31`) for 2020-01-01 to 2020-01-02. Expect a smaller vocabulary and far fewer surviving tracks, a correctness check rather than a reproduction of the perplexity at the bottom of the page. The encoder-decoder itself comes from the t2vec reference implementation ([github.com/boathit/t2vec](https://github.com/boathit/t2vec)); clone it and work from the repository root so `model/`, `data_loader.py`, and `utils.py` are importable.

## Step 1. Query and clean the tracks

Raw AIS is noisy, so `process_interval` pulls a bounding-box query, drops inland and noisy points, splits tracks on three-hour gaps, filters implausible jumps and near-stationary segments, and interpolates everything to one-minute steps so each surviving segment is a clean, continuous trajectory.

```python
import os
import json

import h3
import aisdb
import numpy as np
import geopandas as gpd
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from aisdb.database.dbconn import PostgresDBConn
from aisdb.denoising_encoder import encode_greatcircledistance, InlandDenoising
from aisdb.track_gen import min_speed_filter
from aisdb.database import sqlfcn
from datetime import datetime, timedelta
from tqdm import tqdm

import nest_asyncio
nest_asyncio.apply()

dbconn = PostgresDBConn(hostaddr='127.0.0.1', port=5432, user='postgres',
                        password=os.environ.get('POSTGRES_PASSWORD'), dbname='postgres')


def process_interval(dbconn, start, end):
    qry = aisdb.DBQuery(dbconn=dbconn, start=start, end=end,
                        xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax,
                        callback=aisdb.database.sqlfcn_callbacks.in_bbox_time_validmmsi)
    # decimate=False keeps every reported point instead of curve-decimating them
    rowgen = qry.gen_qry(fcn=sqlfcn.crawl_dynamic_static)
    tracks = aisdb.track_gen.TrackGen(rowgen, decimate=False)
    with InlandDenoising(data_dir='./data/tmp/') as remover:
        cleaned_tracks = remover.filter_noisy_points(tracks)
    # Split on time gaps, drop implausible segments, interpolate every minute.
    track_segments = aisdb.track_gen.split_timedelta(cleaned_tracks, time_split)
    tracks_encoded = encode_greatcircledistance(track_segments, distance_threshold=distance_split, speed_threshold=speed_split)
    tracks_encoded = min_speed_filter(tracks_encoded, minspeed=1)
    tracks_interpolated = aisdb.interp.interp_time(tracks_encoded, step=timedelta(minutes=1))
    return list(tracks_interpolated)
```

## Step 2. Tokenize tracks onto the H3 grid

Each position maps to an H3 cell at resolution 6, and consecutive duplicates collapse into one token that keeps its entry timestamp, turning every trajectory into a sequence of discrete spatial tokens. The study region's bounding box comes from a hexagon-grid shapefile; on the NOAA drop-in, set the four bounds directly.

```python
gdf_hexagons = gpd.read_file('./data/cell/Hexagons_6.shp').to_crs(epsg=4326)
xmin, ymin, xmax, ymax = gdf_hexagons.total_bounds

start_date, end_date = datetime(2023, 1, 1), datetime(2023, 1, 30)
time_split = timedelta(hours=3)
distance_split, speed_split = 10000, 40   # meters, knots
g2h3_vec = np.vectorize(h3.latlng_to_cell)

track_info_list = []
track_list = process_interval(dbconn, start_date, end_date)
for track in tqdm(track_list, total=len(track_list), desc="Vessels", leave=False):
    h3_ids = g2h3_vec(track['lat'], track['lon'], 6)
    timestamps = track['time']
    # Deduplicate consecutive identical cells, keeping the entry timestamp.
    dedup_h3_ids = [h3_ids[0]]
    dedup_timestamps = [timestamps[0]]
    for i in range(1, len(h3_ids)):
        if h3_ids[i] != dedup_h3_ids[-1]:
            dedup_h3_ids.append(h3_ids[i])
            dedup_timestamps.append(timestamps[i])
    track_info_list.append({"mmsi": track['mmsi'], "h3_seq": dedup_h3_ids,
                            "timestamp_seq": dedup_timestamps})
```

## Step 3. Inspect and filter track lengths

Very short tracks carry little sequential structure and very long ones tend to be artifacts (a vessel that never left port, a corrupted timestamp), so look at the length distribution before training and keep tracks between 10 and 300 cells.

```python
import seaborn as sns

def plot_length_distribution(track_lengths):
    plt.figure(figsize=(10, 6))
    sns.histplot(track_lengths, bins=100, kde=True)
    plt.title("Distribution of Track Lengths")
    plt.xlabel("Track Length (number of H3 cells)")
    plt.ylabel("Frequency")
    plt.show()

def map_view(tracks, color=None, line_width=0.5, line_opacity=0.3):
    plt.figure(figsize=(16, 9))
    ax = plt.axes(projection=ccrs.PlateCarree())
    ax.add_feature(cfeature.OCEAN.with_scale('10m'), facecolor='#E0E0E0')
    ax.add_feature(cfeature.LAND.with_scale('10m'), facecolor='#FFE5CC')
    ax.coastlines(resolution='10m')
    for track in tqdm(tracks):
        ax.plot(track['lon'], track['lat'], color=color, linewidth=line_width,
                alpha=line_opacity, transform=ccrs.PlateCarree())
    ax.gridlines(draw_labels=True)
    plt.show()

def hex_view(lats, lons):
    plt.figure(figsize=(8, 8))
    for traj_lat, traj_lon in zip(lats, lons):
        plt.plot(traj_lon, traj_lat, alpha=0.3, linewidth=1)
    plt.xlabel("Longitude")
    plt.ylabel("Latitude")
    plt.title("Test Trajectories")
    plt.axis("equal")

map_view(track_list)
plot_length_distribution([len(t['h3_seq']) for t in track_info_list])
```

<figure><img src="../.gitbook/assets/unknown.png" alt=""><figcaption>Raw AIS trajectories over the Gulf of St. Lawrence approaches and the Nova Scotia coastline, before H3 discretization or length filtering, private PostgreSQL corpus (January 2023).</figcaption></figure>

<figure><img src="../.gitbook/assets/unknown (1).png" alt=""><figcaption>Distribution of AIS track lengths in H3 cells before filtering, private PostgreSQL corpus (January 2023). Most tracks span fewer than 20 cells, with a long tail running out to several hundred.</figcaption></figure>

```python
track_info_list = [t for t in track_info_list if (len(t['h3_seq']) >= 10) & (len(t['h3_seq']) <= 300)]
plot_length_distribution([len(t['h3_seq']) for t in track_info_list])
```

<figure><img src="../.gitbook/assets/unknown (2).png" alt=""><figcaption>Distribution of AIS track lengths in H3 cells after filtering to the 10-300 range, private PostgreSQL corpus (January 2023).</figcaption></figure>

## Step 4. Build the H3 vocabulary

Exactly as in NLP, every unique cell gets an integer index with three reserved for padding, start, and end of sequence; each track is then mapped to its integer sequence, plus lat/lon pairs recovered from the cells for later visualization.

```python
vec_cell_to_latlng = np.vectorize(h3.cell_to_latlng)

all_h3_ids = {h for t in track_info_list for h in t['h3_seq']}

# Reserve 0, 1, 2 for <PAD>, <BOS>, <EOS>.
h3_vocab = {h: i + 3 for i, h in enumerate(sorted(all_h3_ids))}
h3_vocab.update({"<PAD>": 0, "<BOS>": 1, "<EOS>": 2})

for t in track_info_list:
    t["int_seq"] = [h3_vocab[h] for h in t["h3_seq"] if h in h3_vocab]
    t["lat"], t["lon"] = vec_cell_to_latlng(t.get('h3_seq'))
```

## Step 5. Split and write the dataset

The t2vec loader reads aligned text files, `.src` holds each sequence minus its last token, `.trg` the same sequence minus its first, `.lat`/`.lon` the coordinates, and `_trj.t` the full sequence, so we split 60/20/20 and write one line per trajectory.

```python
from sklearn.model_selection import train_test_split

train_tracks, temp_tracks = train_test_split(track_info_list, test_size=0.4, random_state=42)
val_tracks, test_tracks = train_test_split(temp_tracks, test_size=0.5, random_state=42)

def save_data(tracks, prefix, output_dir="data"):
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, f"{prefix}.src"), "w") as f_src, \
         open(os.path.join(output_dir, f"{prefix}.trg"), "w") as f_trg, \
         open(os.path.join(output_dir, f"{prefix}.lat"), "w") as f_lat, \
         open(os.path.join(output_dir, f"{prefix}.lon"), "w") as f_lon, \
         open(os.path.join(output_dir, f"{prefix}_trj.t"), "w") as f_t:
        for t in tracks:
            ids = t["int_seq"]
            f_t.write(" ".join(map(str, ids)) + "\n")
            f_src.write(" ".join(map(str, ids[:-1])) + "\n")
            f_trg.write(" ".join(map(str, ids[1:])) + "\n")
            f_lat.write(" ".join(map(str, t.get('lat'))) + "\n")
            f_lon.write(" ".join(map(str, t.get('lon'))) + "\n")

save_data(train_tracks, "train")
save_data(val_tracks, "val")
save_data(test_tracks, "test")

with open("data/vocab.json", "w") as f:
    json.dump(h3_vocab, f, indent=2)  # the INT index to H3 index mapping

lats = [np.fromstring(line, sep=' ') for line in open("data/train.lat")]
lons = [np.fromstring(line, sep=' ') for line in open("data/train.lon")]
hex_view(lats, lons)
```

<figure><img src="../.gitbook/assets/unknown (3).png" alt=""><figcaption>Held-out test trajectories in raw lat/lon space after H3 tokenization and the train/validation/test split, private PostgreSQL corpus (January 2023).</figcaption></figure>

## Step 6. Train and evaluate

Training combines two objectives, a generative next-cell loss (negative log-likelihood, exactly next-word prediction in NLP) and a discriminative triplet margin loss that pulls embeddings of similar trajectories together and pushes different ones apart. The loop validates and checkpoints every `save_freq` iterations, a plateau scheduler decays the learning rate, and early stopping ends the run when validation stops improving. The upstream t2vec repo also ships a KL-divergence loss weighted by inter-cell distance; plain NLL is enough here.

```python
import shutil
import torch
import torch.nn as nn
from torch.nn.utils import clip_grad_norm_

from model.t2vec import EncoderDecoder
from data_loader import DataLoader
from utils import *
from model.loss import *

PAD = 0

def make_loader(args, prefix, **kw):
    path = lambda ext: os.path.join(args.data, prefix + ext)
    return DataLoader(path(".src"), path(".trg"), path(".lat"), path(".lon"),
                      args.batch, args.bucketsize, **kw)

def init_parameters(model):
    for p in model.parameters():
        p.data.uniform_(-0.1, 0.1)

def savecheckpoint(state, is_best, args):
    torch.save(state, args.checkpoint)
    if is_best:
        shutil.copyfile(args.checkpoint, os.path.join(args.data, 'best_model.pt'))

def validate(valData, model, lossF, args):
    m0, m1 = model
    m0.eval()
    m1.eval()
    num_iteration = (valData.size + args.batch - 1) // args.batch
    total_genloss = 0
    for iteration in range(num_iteration):
        gendata = valData.getbatch_generative()
        with torch.no_grad():
            genloss = genLoss(gendata, m0, m1, lossF, args)
            total_genloss += genloss.item() * gendata.trg.size(1)
    m0.train()
    m1.train()
    return total_genloss / valData.size

def train(args):
    trainData = make_loader(args, "train")
    trainData.load(args.max_num_line)
    valData = make_loader(args, "val", validate=True)
    valData.load()

    criterion = NLLcriterion(args.vocab_size)
    lossF = lambda o, t: criterion(o, t)
    triplet_loss = nn.TripletMarginLoss(margin=1.0, p=2)

    m0 = EncoderDecoder(args.vocab_size, args.embedding_size, args.hidden_size,
                        args.num_layers, args.dropout, args.bidirectional)
    m1 = nn.Sequential(nn.Linear(args.hidden_size, args.vocab_size),
                       nn.LogSoftmax(dim=1))
    if args.cuda and torch.cuda.is_available():
        m0.cuda()
        m1.cuda()
        criterion.cuda()

    m0_optimizer = torch.optim.Adam(m0.parameters(), lr=args.learning_rate)
    m1_optimizer = torch.optim.Adam(m1.parameters(), lr=args.learning_rate)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        m0_optimizer, mode='min', patience=args.lr_decay_patience, min_lr=0, verbose=True)

    best_prec_loss = float('inf')
    init_parameters(m0)
    init_parameters(m1)

    num_iteration = 6700 * 128 // args.batch
    no_improvement_count = 0

    for iteration in range(args.start_iteration, num_iteration):
        m0_optimizer.zero_grad()
        m1_optimizer.zero_grad()
        gendata = trainData.getbatch_generative()
        genloss = genLoss(gendata, m0, m1, lossF, args)
        disloss_cross, disloss_inner = 0, 0
        if args.use_discriminative and iteration % 5 == 0:
            a, p, n = trainData.getbatch_discriminative_cross()
            disloss_cross = disLoss(a, p, n, m0, triplet_loss, args)
            a, p, n = trainData.getbatch_discriminative_inner()
            disloss_inner = disLoss(a, p, n, m0, triplet_loss, args)
        loss = genloss + args.discriminative_w * (disloss_cross + disloss_inner)
        loss.backward()
        clip_grad_norm_(m0.parameters(), args.max_grad_norm)
        clip_grad_norm_(m1.parameters(), args.max_grad_norm)
        m0_optimizer.step()
        m1_optimizer.step()

        if iteration % args.print_freq == 0:
            avg_genloss = genloss.item() / gendata.trg.size(0)
            print(f"Iteration: {iteration}\tGenerative Loss: {avg_genloss:.3f}\t"
                  f"Discriminative Cross Loss: {disloss_cross:.3f}\tDiscriminative Inner Loss: {disloss_inner:.3f}")

        if iteration % args.save_freq == 0 and iteration > 0:
            prec_loss = validate(valData, (m0, m1), lossF, args)
            scheduler.step(prec_loss)
            is_best = prec_loss < best_prec_loss
            if is_best:
                best_prec_loss = prec_loss
                no_improvement_count = 0
            else:
                no_improvement_count += 1
            savecheckpoint({"iteration": iteration, "best_prec_loss": best_prec_loss,
                            "m0": m0.state_dict(), "m1": m1.state_dict(),
                            "m0_optimizer": m0_optimizer.state_dict(),
                            "m1_optimizer": m1_optimizer.state_dict()}, is_best, args)
            if no_improvement_count >= args.early_stopping_patience:
                print(f"No improvement after {args.early_stopping_patience} iterations, early stopping triggered.")
                break

def test(args):
    testData = make_loader(args, "test", validate=True)
    testData.load()

    m0 = EncoderDecoder(args.vocab_size, args.embedding_size, args.hidden_size,
                        args.num_layers, args.dropout, args.bidirectional)
    m1 = nn.Sequential(nn.Linear(args.hidden_size, args.vocab_size),
                       nn.LogSoftmax(dim=1))
    best_model = torch.load(os.path.join(args.data, 'best_model.pt'))
    m0.load_state_dict(best_model["m0"])
    m1.load_state_dict(best_model["m1"])
    m0.eval()
    m1.eval()

    criterion = NLLcriterion(args.vocab_size)
    lossF = lambda o, t: criterion(o, t)
    if args.cuda and torch.cuda.is_available():
        m0.cuda()
        m1.cuda()
        criterion.cuda()

    num_iteration = (testData.size + args.batch - 1) // args.batch
    total_genloss, total_tokens = 0, 0
    with torch.no_grad():
        for iter in range(num_iteration):
            gendata = testData.getbatch_generative()
            genloss = genLoss(gendata, m0, m1, lossF, args)
            total_genloss += genloss.item()
            total_tokens += (gendata.trg != PAD).sum().item()  # count non-pad tokens
            print("Testing genloss at {} iteration is {}".format(iter, total_genloss))

    avg_loss = total_genloss / total_tokens
    perplexity = torch.exp(torch.tensor(avg_loss))
    print(f"[Test] Avg Loss: {avg_loss:.4f} | Perplexity: {perplexity:.2f}")
```

The hyperparameters mirror the t2vec defaults scaled down to this corpus, with the vocabulary size taken from the mapping built in Step 4.

```python
class Args:
    data = 'data/'
    checkpoint = 'data/checkpoint.pt'
    vocab_size = len(h3_vocab)
    embedding_size = 128
    hidden_size = 128
    num_layers = 1
    dropout = 0.1
    max_grad_norm = 1.0
    learning_rate = 1e-2
    lr_decay_patience = 20
    early_stopping_patience = 50
    cuda = torch.cuda.is_available()
    bidirectional = True
    batch = 16
    bucketsize = [(20,30),(30,30),(30,50),(50,50),(50,70),(70,70),(70,100),(100,100)]
    use_discriminative = True
    discriminative_w = 0.1
    max_num_line = 200000
    start_iteration = 0
    generator_batch = 16
    print_freq = 10
    save_freq = 10

args = Args()
train(args)
test(args)
```

## Results

The cumulative generative loss climbs across test batches simply because it is a running sum, not a per-batch average, so read only the final row. Normalized per token, the average loss came out to 0.2309, a perplexity of roughly 1.26.

<details>

<summary>Test-set log: cumulative genloss per iteration and final perplexity</summary>

```
Testing genloss at 0 iteration is 46.40993881225586
Testing genloss at 1 iteration is 83.17555618286133
Testing genloss at 2 iteration is 122.76013565063477
Testing genloss at 3 iteration is 167.81907272338867
Testing genloss at 4 iteration is 223.75146102905273
Testing genloss at 5 iteration is 287.765926361084
Testing genloss at 6 iteration is 328.6252250671387
Testing genloss at 7 iteration is 394.95031356811523
Testing genloss at 8 iteration is 459.411678314209
Testing genloss at 9 iteration is 557.8198432922363
Testing genloss at 10 iteration is 724.5464973449707
Testing genloss at 11 iteration is 876.1395149230957
Testing genloss at 12 iteration is 1020.6461372375488
Testing genloss at 13 iteration is 1277.3499336242676
Testing genloss at 14 iteration is 1416.0101203918457
Testing genloss at 15 iteration is 1742.3399543762207
Testing genloss at 16 iteration is 2101.4984016418457
Testing genloss at 17 iteration is 2319.603458404541
[Test] Avg Loss: 0.2309 | Perplexity: 1.26
```

</details>

A perplexity near 1 means the model is nearly certain about the next cell, which makes sense given how constrained vessel movement is by geography, channels, and traffic separation schemes. Treat it as a sanity check that the preprocessing, vocabulary, and encoder-decoder are wired together correctly, not as a benchmark of embedding quality. Nothing here has yet pulled the encoder's hidden state out and used it for similarity search, route clustering, or anomaly flagging, and that evaluation on the embedding vectors themselves is the natural next step.

## Takeaway

* H3 resolution is the main design choice. Resolution 6 cells span kilometers, so tight maneuvering collapses into a few tokens, while finer resolutions multiply the vocabulary and need more repeated visits per cell to learn from.
* A perplexity of 1.26 on held-out tracks confirms the pipeline works, largely because shipping lanes make the next cell highly predictable.
* The embeddings are the encoder's hidden states, and clustering, similarity search, or anomaly detection on them is where the model pays off.
* One NOAA day validates the wiring end to end but will not reproduce month-scale metrics.

Next, [Using Newtonian PINNs](using-newtonian-pinns.md) returns to continuous coordinate forecasting and adds physics-informed constraints so predicted tracks respect vessel kinematics.
