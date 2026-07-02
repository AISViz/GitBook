---
description: >-
  Build an attention-based encoder-decoder LSTM in PyTorch that forecasts a
  vessel's next positions from its recent AIS track, using AISdb to query,
  clean, and reshape the trajectories for training.
icon: arrow-right-arrow-left
---

# seq2seq in PyTorch

This tutorial builds a sequence-to-sequence LSTM in PyTorch that forecasts where a vessel is heading next from its last 80 AIS fixes. AISdb handles the querying, cleaning, and interpolation of the trajectories, and the model predicts position residuals that decode back to lat/lon on a map. You walk away with a complete forecasting pipeline, from raw AIS messages to a metric error per predicted step.

## What you will learn

* Querying and cleaning vessel tracks with AISdb generators (`DBQuery`, `TrackGen`, denoising, interpolation)
* Turning trajectories into sliding-window tensors for supervised forecasting
* Building an attention-based encoder-decoder LSTM with teacher forcing
* Training with a coordinate-weighted loss plus a smoothness penalty
* Decoding residual predictions back to lat/lon and measuring haversine error

## Prerequisites

```bash
pip install aisdb torch scikit-learn pandas numpy pyproj cartopy matplotlib
```

The run on this page trains against a private SQLite extract of AIS traffic in the Gulf of St. Lawrence, first week of August 2018, so treat `DB_CONNECTION` below as a stand-in for whatever regional extract you have. Without private data, the open NOAA day file [`AIS_2020_01_01.zip`](https://coast.noaa.gov/htdata/CMSP/AISDataHandler/2020/AIS_2020_01_01.zip) works as a drop-in. Decode it with `aisdb.decode_msgs(filepaths=[...], dbconn=dbconn, source='NOAA')` the way [Using Your AIS Data](../tutorials/using-your-ais-data.md) shows, point `DB_CONNECTION` at the result, and swap in the Gulf of Mexico window (`xmin=-98, xmax=-80, ymin=24, ymax=31`, 2020-01-01 to 2020-01-02). Expect a noticeably worse error than the roughly 830 m reported below, since one day of data gives the sliding-window sequencer far fewer long, dense tracks to learn from.

## Step 1. Query training and test tracks

`DBQuery` wraps a time range and a bounding box into a SQL query and hands back a generator of rows, which `TrackGen` vectorizes into per-vessel tracks. The test set comes from a later date range than the training set so the model cannot memorize it.

<figure><img src="../.gitbook/assets/image (45).png" alt=""><figcaption>Query bounding box over the Gulf of St. Lawrence extract, 2018-08-01 to 2018-08-04.</figcaption></figure>

```python
import random
from collections import defaultdict
from datetime import datetime, timedelta

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyproj
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import RobustScaler
from torch.utils.data import DataLoader, TensorDataset

import aisdb
from aisdb import DBConn
from aisdb.database.sqlfcn_callbacks import in_time_bbox
from aisdb.track_gen import TrackGen

DB_CONNECTION = "/home/sqlite_database_file.db"  # replace with your data path
START_DATE = datetime(2018, 8, 1, hour=0)
END_DATE = datetime(2018, 8, 4, hour=2)
XMIN, YMIN, XMAX, YMAX = -64.828126, 46.113933, -58.500001, 49.619290

dbconn = DBConn(dbpath=DB_CONNECTION)

# in_time_bbox filters rows by both the time range and the bounding box.
train_qry = aisdb.DBQuery(dbconn=dbconn, callback=in_time_bbox,
                          start=START_DATE, end=END_DATE,
                          xmin=XMIN, xmax=XMAX, ymin=YMIN, ymax=YMAX)
train_gen = TrackGen(train_qry.gen_qry(verbose=True), decimate=False)

TEST_START_DATE = datetime(2018, 8, 5, hour=0)
TEST_END_DATE = datetime(2018, 8, 6, hour=8)
test_qry = aisdb.DBQuery(dbconn=dbconn, callback=in_time_bbox,
                         start=TEST_START_DATE, end=TEST_END_DATE,
                         xmin=XMIN, xmax=XMAX, ymin=YMIN, ymax=YMAX)
test_gen = TrackGen(test_qry.gen_qry(verbose=True), decimate=False)
```

## Step 2. Preprocess the tracks

Raw AIS is too irregular to feed a model directly. The function below drops near-stationary pings, splits segments that do not belong to the same continuous trip, interpolates to a fixed 5-minute step, keeps only MMSIs with at least 100 points, projects lat/lon into UTM meters with `pyproj`, encodes course over ground as sine and cosine because it wraps at 360 degrees, and scales every feature with a `RobustScaler` fit on the training set only.

```python
def preprocess_aisdb_tracks(tracks_gen, proj, sog_scaler=None, feature_scaler=None, fit_scaler=False):
    # Chain the AISdb generators first, then materialize the tracks.
    tracks_gen = aisdb.remove_pings_wrt_speed(tracks_gen, 0.1)
    tracks_gen = aisdb.encode_greatcircledistance(tracks_gen, distance_threshold=50000,
                                                  minscore=1e-5, speed_threshold=50)
    tracks_gen = aisdb.interp_time(tracks_gen, step=timedelta(minutes=5))
    tracks = list(tracks_gen)

    tracks_by_mmsi = defaultdict(list)
    for track in tracks:
        tracks_by_mmsi[track['mmsi']].append(track)

    # Short tracks give the model almost nothing to learn from.
    valid_tracks = []
    for mmsi, mmsi_tracks in tracks_by_mmsi.items():
        if all(len(t['time']) >= 100 for t in mmsi_tracks):
            valid_tracks.extend(mmsi_tracks)

    rows = []
    for track in valid_tracks:
        sog = track.get('sog', [np.nan] * len(track['time']))
        cog = track.get('cog', [np.nan] * len(track['time']))
        for i in range(len(track['time'])):
            x, y = proj(track['lon'][i], track['lat'][i])
            cog_rad = np.radians(cog[i]) if cog[i] is not None else np.nan
            rows.append({
                'mmsi': track['mmsi'], 'x': x, 'y': y, 'sog': sog[i],
                'cog_sin': np.sin(cog_rad) if not np.isnan(cog_rad) else np.nan,
                'cog_cos': np.cos(cog_rad) if not np.isnan(cog_rad) else np.nan,
                'timestamp': pd.to_datetime(track['time'][i], errors='coerce'),
            })

    df = pd.DataFrame(rows).replace([np.inf, -np.inf], np.nan)
    df = df.dropna(subset=['x', 'y', 'sog', 'cog_sin', 'cog_cos'])

    feature_cols = ['x', 'y', 'sog', 'cog_sin', 'cog_cos']
    if fit_scaler:
        sog_scaler = RobustScaler()
        df['sog_scaled'] = sog_scaler.fit_transform(df[['sog']])
        feature_scaler = RobustScaler()
        df[feature_cols] = feature_scaler.fit_transform(df[feature_cols])
    else:
        df['sog_scaled'] = sog_scaler.transform(df[['sog']])
        df[feature_cols] = feature_scaler.transform(df[feature_cols])

    return df, sog_scaler, feature_scaler


proj = pyproj.Proj(proj='utm', zone=20, ellps='WGS84')  # lat/lon -> meters, zone 20 fits this extract

train_df, sog_scaler, feature_scaler = preprocess_aisdb_tracks(train_gen, proj, fit_scaler=True)
test_df, _, _ = preprocess_aisdb_tracks(test_gen, proj, sog_scaler=sog_scaler,
                                        feature_scaler=feature_scaler, fit_scaler=False)
```

## Step 3. Create sequences and loaders

A sliding window turns each trajectory into supervised examples, 80 input steps predicting the next 2. Splitting train and validation by MMSI keeps every vessel on one side of the split, so validation measures generalization to unseen vessels rather than unseen windows of seen ones.

```python
def create_sequences(df, features, input_size=80, output_size=2, step=1):
    X_list, Y_list = [], []
    for mmsi in df['mmsi'].unique():
        sub = df[df['mmsi'] == mmsi].sort_values('timestamp')[features].to_numpy()
        for i in range(0, len(sub) - input_size - output_size + 1, step):
            X_list.append(sub[i:i + input_size])
            Y_list.append(sub[i + input_size:i + input_size + output_size])
    return torch.tensor(X_list, dtype=torch.float32), torch.tensor(Y_list, dtype=torch.float32)


features = ['x', 'y', 'cog_sin', 'cog_cos', 'sog_scaled']
mmsis = train_df['mmsi'].unique()
train_mmsi, val_mmsi = train_test_split(mmsis, test_size=0.2, random_state=42, shuffle=True)

train_X, train_Y = create_sequences(train_df[train_df['mmsi'].isin(train_mmsi)], features)
val_X, val_Y = create_sequences(train_df[train_df['mmsi'].isin(val_mmsi)], features)
test_X, test_Y = create_sequences(test_df, features)

batch_size = 64
train_dl = DataLoader(TensorDataset(train_X, train_Y), batch_size=batch_size, shuffle=True)
val_dl = DataLoader(TensorDataset(val_X, val_Y), batch_size=batch_size, shuffle=False)
test_dl = DataLoader(TensorDataset(test_X, test_Y), batch_size=batch_size)
```

## Step 4. Define the model and losses

The encoder LSTM compresses the 80-step history into hidden states, and the decoder unrolls two future steps, attending over the encoder outputs at each step ([Bahdanau et al., 2015](https://arxiv.org/abs/1409.0473)) and predicting a residual that is added to the last observed position. Anchoring every forecast to the vessel's current fix keeps predictions physically plausible, and teacher forcing occasionally feeds the decoder ground truth during training so multi-step errors do not compound early ([Sutskever et al., 2014](https://arxiv.org/abs/1409.3215)).

```python
class Seq2SeqLSTM(nn.Module):
    def __init__(self, input_size, hidden_size, input_steps, output_steps):
        super().__init__()
        self.input_steps = input_steps
        self.output_steps = output_steps
        self.encoder = nn.LSTM(input_size, hidden_size, num_layers=2, dropout=0.3, batch_first=True)
        self.decoder = nn.LSTMCell(input_size, hidden_size)
        self.attn = nn.Linear(hidden_size + hidden_size, input_steps)
        self.attn_combine = nn.Linear(hidden_size + input_size, input_size)
        self.output_layer = nn.Sequential(
            nn.Linear(hidden_size, hidden_size // 2),
            nn.ReLU(),
            nn.Linear(hidden_size // 2, input_size),
        )

    def forward(self, x, target_seq=None, teacher_forcing_ratio=0.5):
        """x: [B, T_in, F] -> [B, T_out, F], with x,y decoded as last_obs + residuals."""
        encoder_outputs, (h, c) = self.encoder(x)
        h, c = h[-1], c[-1]

        last_obs = x[:, -1, :]
        last_xy = last_obs[:, :2]
        decoder_input = last_obs
        outputs = []

        for t in range(self.output_steps):
            attn_weights = torch.softmax(self.attn(torch.cat((h, c), dim=1)), dim=1)
            context = torch.bmm(attn_weights.unsqueeze(1), encoder_outputs).squeeze(1)
            dec_in = self.attn_combine(torch.cat((decoder_input, context), dim=1))
            h, c = self.decoder(dec_in, (h, c))

            # Residual applies to x,y only; the other features are predicted directly.
            residual = self.output_layer(h)
            out = torch.cat([residual[:, :2] + last_xy, residual[:, 2:]], dim=1)
            outputs.append(out.unsqueeze(1))

            # Teacher forcing feeds the ground-truth step; otherwise autoregress.
            if self.training and target_seq is not None and t < target_seq.size(1) \
                    and random.random() < teacher_forcing_ratio:
                decoder_input = target_seq[:, t, :]
                last_xy = decoder_input[:, :2]
            else:
                decoder_input = out
                last_xy = out[:, :2]

        return torch.cat(outputs, dim=1)


def weighted_coord_loss(pred, target, coord_weight=5.0, reduction='mean'):
    """Weight coordinate errors (first two dims) above the auxiliary features."""
    coord_loss = F.smooth_l1_loss(pred[..., :2], target[..., :2], reduction=reduction)
    aux_loss = F.smooth_l1_loss(pred[..., 2:], target[..., 2:], reduction=reduction)
    return coord_weight * coord_loss + aux_loss


def xy_smoothness_loss(seq_full):
    """L2 penalty on velocity and acceleration of the x,y channels."""
    xy = seq_full[..., :2]
    v = xy[:, 1:, :] - xy[:, :-1, :]
    a = v[:, 1:, :] - v[:, :-1, :]
    return (v ** 2).mean() * 0.05 + (a ** 2).mean() * 0.5
```

## Step 5. Train

The loss combines the coordinate-weighted data term with a smoothness penalty that decays over epochs, and the best epoch by validation loss is checkpointed to disk. Seeds are fixed so the run is reproducible.

```python
def train_model(model, loader, val_dl, optimizer, device, epochs=50,
                coord_weight=5.0, smooth_w_init=1e-3):
    best_loss = float('inf')
    best_state = None
    for epoch in range(epochs):
        model.train()
        total_loss = total_data_loss = total_smooth_loss = 0.0
        for batch_x, batch_y in loader:
            batch_x, batch_y = batch_x.to(device), batch_y.to(device)

            # Targets become residuals relative to the previous position.
            y_start = batch_x[:, -1:, :2]
            residual_y = batch_y.clone()
            residual_y[..., :2] = batch_y[..., :2] - torch.cat([y_start, batch_y[:, :-1, :2]], dim=1)

            optimizer.zero_grad()
            pred_residuals = model(batch_x, target_seq=residual_y, teacher_forcing_ratio=0.5)
            loss_data = weighted_coord_loss(pred_residuals, residual_y, coord_weight=coord_weight)

            # The smoothness term needs the absolute xy sequence back.
            pred_xy = torch.cumsum(pred_residuals[..., :2], dim=1) + y_start
            full_seq = torch.cat([batch_x[..., :2], pred_xy], dim=1)
            loss_smooth = xy_smoothness_loss(full_seq)

            smooth_weight = smooth_w_init * max(0.1, 1.0 - epoch / 30.0)
            loss = loss_data + smooth_weight * loss_smooth
            if torch.isnan(loss) or torch.isinf(loss):
                print("Skipping batch due to NaN/inf loss.")
                continue

            loss.backward()
            optimizer.step()
            total_loss += loss.item()
            total_data_loss += loss_data.item()
            total_smooth_loss += loss_smooth.item()

        avg_loss = total_loss / len(loader)
        print(f"Epoch {epoch+1:02d} | Total: {avg_loss:.6f} | Data: {total_data_loss/len(loader):.6f} | Smooth: {total_smooth_loss/len(loader):.6f}")

        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for xb, yb in val_dl:
                xb, yb = xb.to(device), yb.to(device)
                y_start = xb[:, -1:, :2]
                residual_y = yb.clone()
                residual_y[..., :2] = yb[..., :2] - torch.cat([y_start, yb[:, :-1, :2]], dim=1)
                pred_residuals = model(xb, target_seq=residual_y, teacher_forcing_ratio=0.0)
                data_loss = weighted_coord_loss(pred_residuals, residual_y, coord_weight=coord_weight)
                pred_xy = torch.cumsum(pred_residuals[..., :2], dim=1) + y_start
                full_seq = torch.cat([xb[..., :2], pred_xy], dim=1)
                val_loss += (data_loss + smooth_weight * xy_smoothness_loss(full_seq)).item()

        val_loss /= len(val_dl)
        print(f"           Val Loss: {val_loss:.6f}")
        if val_loss < best_loss:
            best_loss, best_state = val_loss, model.state_dict()

    if best_state is not None:
        torch.save(best_state, "best_model_seq2seq_residual_xy_08302.pth")
        print("Best model saved")


SEED = 42
torch.manual_seed(SEED)
np.random.seed(SEED)
random.seed(SEED)
torch.cuda.manual_seed_all(SEED)
torch.backends.cudnn.deterministic = True
torch.backends.cudnn.benchmark = False

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = Seq2SeqLSTM(input_size=5, hidden_size=64, input_steps=80, output_steps=2).to(device)
optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

train_model(model, train_dl, val_dl, optimizer, device)
```

## Step 6. Evaluate on held-out tracks

A small decimal loss can hide predictions that land far from the real position, so the evaluation decodes the residuals back to lat/lon, measures haversine error in meters, and plots the track on a map as the sanity check. The residuals are decoded by multiplying with the per-axis standard deviation of the true training residuals in meters, then cumulative-summing from the last observed position.

```python
def inverse_xy_only(xy_scaled, scaler):
    """Inverse-transform the x,y columns only (StandardScaler or RobustScaler)."""
    center = scaler.mean_[:2] if hasattr(scaler, "mean_") else scaler.center_[:2]
    return xy_scaled * scaler.scale_[:2] + center


def haversine(lon1, lat1, lon2, lat2):
    """Distance in meters between two lon/lat points."""
    lon1, lat1, lon2, lat2 = map(np.radians, [lon1, lat1, lon2, lat2])
    a = np.sin((lat2 - lat1) / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2.0) ** 2
    return 2 * 6371000.0 * np.arcsin(np.sqrt(a))


def evaluate_with_errors(model, test_dl, proj, feature_scaler, device,
                         residual_std, num_batches=1, dup_tol=1e-4):
    """Decode residual predictions to lat/lon, print per-step errors, plot the track."""
    model.eval()
    errors_all, batches = [], 0
    with torch.no_grad():
        for xb, yb in test_dl:
            xb, yb = xb.to(device), yb.to(device)
            pred = model(xb, teacher_forcing_ratio=0.0)

            # First sample of the batch for diagnostics and plotting.
            input_xy_s = xb[0, :, :2].cpu().numpy()
            real_xy_s = yb[0, :, :2].cpu().numpy()
            pred_xy_s = pred[0, :, :2].cpu().numpy()

            last_obs_xy_m = inverse_xy_only(input_xy_s[-1], feature_scaler)
            pred_xy_m = np.cumsum(pred_xy_s * residual_std, axis=0) + last_obs_xy_m

            # Interpolation can duplicate the last observation as the first target.
            if real_xy_s.shape[0] >= 1 and np.allclose(real_xy_s[0], input_xy_s[-1], atol=dup_tol):
                real_xy_s = real_xy_s[1:]

            min_len = min(pred_xy_m.shape[0], real_xy_s.shape[0])
            if min_len == 0:
                batches += 1
                if batches >= num_batches:
                    break
                continue
            pred_xy_m = pred_xy_m[:min_len]
            real_xy_m = inverse_xy_only(real_xy_s[:min_len], feature_scaler)
            input_xy_m = inverse_xy_only(input_xy_s, feature_scaler)

            lon_in, lat_in = proj(input_xy_m[:, 0], input_xy_m[:, 1], inverse=True)
            lon_real, lat_real = proj(real_xy_m[:, 0], real_xy_m[:, 1], inverse=True)
            lon_pred, lat_pred = proj(pred_xy_m[:, 0], pred_xy_m[:, 1], inverse=True)

            print("\n=== Predicted vs True (lat/lon) ===")
            print(f"{'t':>3} | {'lon_true':>9} | {'lat_true':>9} | {'lon_pred':>9} | {'lat_pred':>9} | {'err_m':>9}")
            errors = []
            for t in range(len(lon_real)):
                err_m = haversine(lon_real[t], lat_real[t], lon_pred[t], lat_pred[t])
                errors.append(err_m)
                print(f"{t:3d} | {lon_real[t]:9.5f} | {lat_real[t]:9.5f} | {lon_pred[t]:9.5f} | {lat_pred[t]:9.5f} | {err_m:9.2f}")
            errors_all.append(errors)

            fig = plt.figure(figsize=(8, 6))
            ax = plt.axes(projection=ccrs.PlateCarree())
            all_lons = np.concatenate([lon_in, lon_real, lon_pred])
            all_lats = np.concatenate([lat_in, lat_real, lat_pred])
            ax.set_extent([all_lons.min() - 0.01, all_lons.max() + 0.01,
                           all_lats.min() - 0.01, all_lats.max() + 0.01],
                          crs=ccrs.PlateCarree())
            ax.add_feature(cfeature.COASTLINE)
            ax.add_feature(cfeature.LAND, facecolor="lightgray")
            ax.add_feature(cfeature.OCEAN, facecolor="lightblue")
            ax.plot(lon_in, lat_in, "o-", label="history", transform=ccrs.PlateCarree(),
                    markersize=6, linewidth=2)
            ax.plot(lon_real, lat_real, "o-", label="true", transform=ccrs.PlateCarree(),
                    markersize=6, linewidth=2)
            ax.plot(lon_pred, lat_pred, "x--", label="pred", transform=ccrs.PlateCarree(),
                    markersize=8, linewidth=2)
            ax.legend()
            plt.show()

            batches += 1
            if batches >= num_batches:
                break

    if errors_all:
        errors_all = np.array(errors_all)
        print("\n=== Summary (meters) ===")
        for t, v in enumerate(errors_all.mean(axis=0)):
            print(f"t={t} mean error: {v:.2f} m")
        print(f"mean over horizon: {errors_all.mean():.2f} m, median: {np.median(errors_all):.2f} m")


# Per-axis std of the true xy residuals in meters, used to decode predictions.
all_resids = []
for i in range(train_X.shape[0]):
    last_obs_m = inverse_xy_only(train_X[i, -1, :2].numpy(), feature_scaler)
    true_m = inverse_xy_only(train_Y[i, :, :2].numpy(), feature_scaler)
    if true_m.shape[0] == 0:
        continue
    resid0 = (true_m[0] - last_obs_m)[None, :]
    resids = np.vstack([resid0, np.diff(true_m, axis=0)]) if true_m.shape[0] > 1 else resid0
    all_resids.append(resids)

residual_std = np.std(np.vstack(all_resids), axis=0)
print("Computed residual_std (meters):", residual_std)

best_model = Seq2SeqLSTM(input_size=5, hidden_size=64, input_steps=80, output_steps=2).to(device)  # best epoch, not last
best_model.load_state_dict(torch.load("best_model_seq2seq_residual_xy_08302.pth", map_location=device))
best_model.eval()

evaluate_with_errors(best_model, test_dl, proj, feature_scaler, device,
                     residual_std=residual_std, num_batches=1)
```

## Results

The call above evaluates a single test batch (`num_batches=1`), decoding the residual predictions back into lat/lon and printing a predicted-vs-true table.

Predicted vs True (lat/lon)

<table><thead><tr><th width="64.79998779296875">t</th><th>lon_true</th><th>lon_pred</th><th>lat_true</th><th>lat_pred</th><th>Error (in m)</th></tr></thead><tbody><tr><td>0</td><td>-61.69744</td><td> -61.70585</td><td>43.22816</td><td>43.22385</td><td> 833.31 m</td></tr></tbody></table>

Summary (meters)\
t=0 mean error: 833.31 m\
mean over horizon: 833.31 m, median: 833.31 m

That 833 meter figure is a single two-step window from one batch, not an average across the whole test set, so treat it as illustrative rather than a benchmark. What it does show is that the residual decoding is behaving. If the scaler or the cumulative sum step were wrong, the predicted point would land tens of kilometers off or on the wrong side of the coastline instead of a few hundred meters short of the real fix.

<figure><img src="../.gitbook/assets/image (46).png" alt=""><figcaption>Predicted vs. true two-step continuation for a held-out track, Gulf of St. Lawrence extract, test window 2018-08-05 to 2018-08-06.</figcaption></figure>

The predicted marker sits close to the true one and on the same heading as the input history, which is what a residual decoder anchored to the last observed position should produce. Error grows with the output horizon and with sharp maneuvers, since the model only sees the pattern in its input window and has no notion of destination or intent.

## Takeaway

* AISdb's generator chain (`remove_pings_wrt_speed`, `encode_greatcircledistance`, `interp_time`) turns raw AIS into model-ready tracks in a few lines.
* Predicting position residuals anchored to the last fix keeps forecasts physically plausible, and decoding mistakes show up on the map immediately.
* The 833 m error is one illustrative window under a single split and seed; cross-validate across time windows and vessel types before trusting the number.
* UTM zone 20 and the fitted scalers are specific to this region and season, so update the projection and refit the scalers when you move the pipeline elsewhere.

Next, [AutoEncoders in Keras](autoencoders-in-keras.md) tackles the same forecasting problem with a GRU-based encoder-decoder and teacher forcing, this time in Keras.
