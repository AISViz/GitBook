---
description: >-
  A physics-informed Seq2Seq model that penalizes unrealistic velocity and
  acceleration in predicted vessel tracks, so forecasts stay kinematically
  plausible even when AIS data is sparse or noisy.
icon: code-pull-request
---

# Using Newtonian PINNs

Purely statistical Seq2Seq models can forecast vessel tracks that look plausible yet turn or accelerate in ways no real ship can. This tutorial builds NPINN, an attention-based Seq2Seq LSTM trained under a combined data-fidelity and kinematic-smoothness loss, so predicted trajectories respect how vessels actually move. You walk away with a complete pipeline, from AISdb query and cleaning through training to an evaluation that reports errors in real meters on a held-out time window.

## What you will learn

* Cleaning, linking, and interpolating AIS tracks into fixed-interval UTM features with AISdb
* Building sliding-window Seq2Seq datasets that predict future position residuals
* Training an attention LSTM with a physics-inspired penalty on velocity and acceleration
* Evaluating forecasts in meters with haversine errors and trajectory-length checks

## Prerequisites

```bash
pip install aisdb torch scikit-learn pyproj joblib pandas cartopy matplotlib
```

The run shown on this page trained on a private regional database built from AISdb's Meridian receiver network, covering the Gulf of St. Lawrence and Cabot Strait over a few days in August 2018, with a test window that starts after training ends so the model must extrapolate to traffic it never saw. If you lack a comparable database, the open NOAA day file works as a drop-in. Download `AIS_2020_01_01.zip` from [coast.noaa.gov](https://coast.noaa.gov/htdata/CMSP/AISDataHandler/2020/AIS_2020_01_01.zip), decode the extracted CSV with `aisdb.decode_msgs(filepaths=[...], dbconn=dbconn, source="NOAA")` into a SQLite database, point `DB_CONNECTION` at it, set the bounding box to `-98, 24, -80, 31`, and set the dates to 2020-01-01 through 2020-01-02. One day cannot supply a genuinely unseen test window, so treat a NOAA run as a pipeline check. The numbers and figures below come from the private multi-day dataset.

## Step 1. Imports and configuration

Everything the pipeline needs lands in one place, including the training window, the later held-out test window, the bounding box, and the UTM projection that converts lat/lon into meters for the physics loss.

```python
import json
import random
from collections import defaultdict
from datetime import datetime, timedelta

import joblib
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
from aisdb import SQLiteDBConn, TrackGen
from aisdb.database.sqlfcn_callbacks import in_bbox_time

DB_CONNECTION = "/home/sqlite_database_file.db"  # replace with your data path
START_DATE = datetime(2018, 8, 1, hour=0)
END_DATE = datetime(2018, 8, 4, hour=2)
TEST_START_DATE = datetime(2018, 8, 5, hour=0)
TEST_END_DATE = datetime(2018, 8, 6, hour=8)
XMIN, YMIN, XMAX, YMAX = -64.828126, 46.113933, -58.500001, 49.619290

dbconn = SQLiteDBConn(dbpath=DB_CONNECTION)
# Cartesian projection used to convert lat/lon into meters for the physics loss
proj = pyproj.Proj(proj='utm', zone=20, ellps='WGS84')
```

## Step 2. Preprocess tracks into model-ready features

Raw AIS is noisy and irregularly sampled, so AISdb first drops near-stationary pings, links segments by great-circle score, and interpolates to fixed 5-minute steps. The function then keeps vessels whose tracks all have at least 100 pings, projects positions to UTM meters, encodes course as sine and cosine to avoid the 359-to-0 degree jump, computes per-step deltas, and scales everything with outlier-resistant `RobustScaler`s.

```python
def preprocess_aisdb_tracks(tracks_gen, proj, sog_scaler=None,
                            feature_scaler=None, delta_scaler=None,
                            fit_scaler=False):
    tracks_gen = aisdb.remove_pings_wrt_speed(tracks_gen, 0.1)
    tracks_gen = aisdb.encode_greatcircledistance(
        tracks_gen, distance_threshold=50000, minscore=1e-5, speed_threshold=50)
    tracks_gen = aisdb.interp_time(tracks_gen, step=timedelta(minutes=5))
    tracks = list(tracks_gen)

    tracks_by_mmsi = defaultdict(list)
    for track in tracks:
        tracks_by_mmsi[track['mmsi']].append(track)
    # Keep only vessels whose tracks are all long enough for stable windows.
    valid_tracks = []
    for mmsi, mmsi_tracks in tracks_by_mmsi.items():
        if all(len(t['time']) >= 100 for t in mmsi_tracks):
            valid_tracks.extend(mmsi_tracks)

    rows = []
    for track in valid_tracks:
        sog = track.get('sog', [np.nan]*len(track['time']))
        cog = track.get('cog', [np.nan]*len(track['time']))
        for i in range(len(track['time'])):
            x, y = proj(track['lon'][i], track['lat'][i])
            cog_rad = np.radians(cog[i]) if cog[i] is not None else np.nan
            rows.append({
                'mmsi': track['mmsi'], 'x': x, 'y': y, 'sog': sog[i],
                'cog_sin': np.sin(cog_rad) if not np.isnan(cog_rad) else np.nan,
                'cog_cos': np.cos(cog_rad) if not np.isnan(cog_rad) else np.nan,
                'timestamp': pd.to_datetime(track['time'][i], unit='s', errors='coerce')
            })

    df = pd.DataFrame(rows).replace([np.inf, -np.inf], np.nan)
    df = df.dropna(subset=['x', 'y', 'sog', 'cog_sin', 'cog_cos'])
    # Per-vessel deltas capture local motion dynamics.
    df = df.sort_values(["mmsi", "timestamp"])
    df["dx"] = df.groupby("mmsi")["x"].diff().fillna(0)
    df["dy"] = df.groupby("mmsi")["y"].diff().fillna(0)

    feature_cols = ['x', 'y', 'sog', 'cog_sin', 'cog_cos']
    delta_cols = ['dx', 'dy']
    if fit_scaler:
        sog_scaler = RobustScaler()
        df['sog_scaled'] = sog_scaler.fit_transform(df[['sog']])
        feature_scaler = RobustScaler()
        df[feature_cols] = feature_scaler.fit_transform(df[feature_cols])
        delta_scaler = RobustScaler()
        df[delta_cols] = delta_scaler.fit_transform(df[delta_cols])
    else:
        df['sog_scaled'] = sog_scaler.transform(df[['sog']])
        df[feature_cols] = feature_scaler.transform(df[feature_cols])
        df[delta_cols] = delta_scaler.transform(df[delta_cols])
    return df, sog_scaler, feature_scaler, delta_scaler
```

## Step 3. Query, build sequences, and checkpoint

The training query fits fresh scalers while the test query reuses them, keeping both windows on the same scale. A window of 80 past steps predicts the next 2 residual movements, vessels are split between training and validation by MMSI so no vessel leaks across the split, and everything is serialized once so later sessions skip the query and preprocessing.

```python
def window_tracks(start, end):
    qry = aisdb.DBQuery(dbconn=dbconn, callback=in_bbox_time, start=start, end=end,
                        xmin=XMIN, xmax=XMAX, ymin=YMIN, ymax=YMAX)
    return TrackGen(qry.gen_qry(verbose=True), decimate=False)


train_df, sog_scaler, feature_scaler, delta_scaler = preprocess_aisdb_tracks(
    window_tracks(START_DATE, END_DATE), proj, fit_scaler=True)
test_df, _, _, _ = preprocess_aisdb_tracks(
    window_tracks(TEST_START_DATE, TEST_END_DATE), proj, sog_scaler=sog_scaler,
    feature_scaler=feature_scaler, delta_scaler=delta_scaler, fit_scaler=False)


def create_sequences(df, features, input_size=80, output_size=2, step=1):
    # X holds past windows of absolute features, Y the future (dx, dy) residuals.
    X_list, Y_list = [], []
    for mmsi in df['mmsi'].unique():
        sub = df[df['mmsi'] == mmsi].sort_values('timestamp').copy()
        feat_arr = sub[features].to_numpy()
        dxdy_arr = sub[['dx', 'dy']].to_numpy()  # residuals already scaled
        for i in range(0, len(sub) - input_size - output_size + 1, step):
            X_list.append(feat_arr[i : i + input_size])
            Y_list.append(dxdy_arr[i + input_size : i + input_size + output_size])
    return torch.tensor(X_list, dtype=torch.float32), torch.tensor(Y_list, dtype=torch.float32)


features = ['x', 'y', 'dx', 'dy', 'cog_sin', 'cog_cos', 'sog_scaled']
mmsis = train_df['mmsi'].unique()
train_mmsi, val_mmsi = train_test_split(mmsis, test_size=0.2, random_state=42, shuffle=True)

train_X, train_Y = create_sequences(train_df[train_df['mmsi'].isin(train_mmsi)], features)
val_X, val_Y = create_sequences(train_df[train_df['mmsi'].isin(val_mmsi)], features)
test_X, test_Y = create_sequences(test_df, features)

torch.save({'train_X': train_X, 'train_Y': train_Y, 'val_X': val_X,
            'val_Y': val_Y, 'test_X': test_X, 'test_Y': test_Y}, 'datasets_npin.pt')
joblib.dump(feature_scaler, "npinn_feature_scaler.pkl")
joblib.dump(sog_scaler, "npinn_sog_scaler.pkl")
joblib.dump(delta_scaler, "npinn_delta_scaler.pkl")
with open("npinn_proj_params.json", "w") as f:
    json.dump({'proj': 'utm', 'zone': 20, 'ellps': 'WGS84'}, f)

batch_size = 64
train_dl = DataLoader(TensorDataset(train_X, train_Y), batch_size=batch_size, shuffle=True)
val_dl = DataLoader(TensorDataset(val_X, val_Y), batch_size=batch_size, shuffle=False)
test_dl = DataLoader(TensorDataset(test_X, test_Y), batch_size=batch_size)
```

## Step 4. Define the Seq2Seq model

An encoder LSTM summarizes the 80 past steps, and a decoder LSTMCell emits one residual at a time while an attention head picks which parts of the history matter for each step. Predicted residuals accumulate onto the last observed position to rebuild absolute coordinates, with teacher forcing on half the steps during training.

```python
class Seq2SeqLSTM(nn.Module):
    def __init__(self, input_size, hidden_size, input_steps, output_steps):
        super().__init__()
        self.input_steps = input_steps
        self.output_steps = output_steps
        self.encoder = nn.LSTM(input_size, hidden_size, num_layers=2, dropout=0.3, batch_first=True)
        self.decoder = nn.LSTMCell(input_size, hidden_size)
        self.attn = nn.Linear(hidden_size * 2, input_steps)
        self.attn_combine = nn.Linear(hidden_size + input_size, input_size)
        # Output only x,y residuals (added to last observed pos)
        self.output_layer = nn.Sequential(
            nn.Linear(hidden_size, hidden_size // 2),
            nn.ReLU(),
            nn.Linear(hidden_size // 2, 2)
        )

    def forward(self, x, target_seq=None, teacher_forcing_ratio=0.5):
        encoder_outputs, (h, c) = self.encoder(x)
        h, c = h[-1], c[-1]
        last_obs = x[:, -1, :2]      # last observed absolute x,y
        decoder_input = x[:, -1, :]  # full feature vector

        outputs = []
        for t in range(self.output_steps):
            attn_weights = torch.softmax(self.attn(torch.cat((h, c), dim=1)), dim=1)
            context = torch.bmm(attn_weights.unsqueeze(1), encoder_outputs).squeeze(1)
            dec_in = self.attn_combine(torch.cat((decoder_input, context), dim=1))
            h, c = self.decoder(dec_in, (h, c))
            residual_xy = self.output_layer(h)
            out_xy = residual_xy + last_obs
            outputs.append(out_xy.unsqueeze(1))

            if self.training and target_seq is not None and t < target_seq.size(1) and random.random() < teacher_forcing_ratio:
                decoder_input = torch.cat([target_seq[:, t, :2], decoder_input[:, 2:]], dim=1)
                last_obs = target_seq[:, t, :2]
            else:
                decoder_input = torch.cat([out_xy, decoder_input[:, 2:]], dim=1)
                last_obs = out_xy
        return torch.cat(outputs, dim=1)  # (batch, output_steps, 2)
```

## Step 5. Define the NPINN loss and training loop

The physics enters through the loss (the idea traces back to physics-informed neural networks, [Raissi et al., 2019](https://doi.org/10.1016/j.jcp.2018.10.045)). First differences of the predicted path approximate velocity and second differences approximate acceleration, so penalizing both keeps trajectories kinematically smooth, while a smooth L1 term keeps them close to the observed positions. The smoothness weight decays over the first 30 epochs, letting the constraint guide early training without capping final accuracy.

```python
def weighted_coord_loss(pred, target, coord_weight=5.0, reduction='mean'):
    return F.smooth_l1_loss(pred, target, reduction=reduction)


def xy_npinn_smoothness_loss(seq_full, coord_min=None, coord_max=None):
    # NPINN-inspired smoothness penalty on xy coordinates; seq_full: [B, T, 2]
    xy = seq_full[..., :2]
    if coord_min is not None and coord_max is not None:
        xy_norm = (xy - coord_min) / (coord_max - coord_min + 1e-8)
        xy_norm = 2 * (xy_norm - 0.5)  # [-1,1]
    else:
        xy_norm = xy
    v = xy_norm[:, 1:, :] - xy_norm[:, :-1, :]   # velocity proxy
    a = v[:, 1:, :] - v[:, :-1, :]               # acceleration proxy
    return (v**2).mean() * 0.05 + (a**2).mean() * 0.5


def train_model(model, loader, val_dl, optimizer, device, epochs=50,
                smooth_w_init=1e-3, coord_min=None, coord_max=None):
    best_loss = float('inf')
    best_state = None
    for epoch in range(epochs):
        model.train()
        total_loss = total_data_loss = total_smooth_loss = 0.0
        for batch_x, batch_y in loader:
            batch_x, batch_y = batch_x.to(device), batch_y.to(device)
            optimizer.zero_grad()
            pred_xy = model(batch_x, target_seq=batch_y, teacher_forcing_ratio=0.5)
            loss_data = weighted_coord_loss(pred_xy, batch_y)
            full_seq = torch.cat([batch_x[:, :, :2], pred_xy], dim=1)  # observed + predicted
            loss_smooth = xy_npinn_smoothness_loss(full_seq, coord_min, coord_max)
            smooth_weight = smooth_w_init * max(0.1, 1.0 - epoch / 30.0)
            loss = loss_data + smooth_weight * loss_smooth
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
            total_data_loss += loss_data.item()
            total_smooth_loss += loss_smooth.item()

        avg_loss = total_loss / len(loader)
        print(f"Epoch {epoch+1} | Total: {avg_loss:.6f} | Data: {total_data_loss/len(loader):.6f} | Smooth: {total_smooth_loss/len(loader):.6f}")

        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for xb, yb in val_dl:
                xb, yb = xb.to(device), yb.to(device)
                pred_xy = model(xb, target_seq=yb, teacher_forcing_ratio=0.0)
                data_loss = weighted_coord_loss(pred_xy, yb)
                full_seq = torch.cat([xb[..., :2], pred_xy], dim=1)
                loss_smooth = xy_npinn_smoothness_loss(full_seq, coord_min, coord_max)
                val_loss += (data_loss + smooth_weight * loss_smooth).item()
        val_loss /= len(val_dl)
        print(f"           Val Loss: {val_loss:.6f}")

        if val_loss < best_loss:
            best_loss = val_loss
            best_state = model.state_dict()

    if best_state is not None:
        torch.save(best_state, "best_model_NPINN.pth")
        print("Best model saved")
```

## Step 6. Train

Fixed seeds and deterministic CuDNN make the run reproducible, and the global min and max of the training coordinates normalize the smoothness penalty so its magnitude does not depend on where the region sits in UTM space.

```python
SEED = 42
torch.manual_seed(SEED)
np.random.seed(SEED)
random.seed(SEED)
torch.cuda.manual_seed_all(SEED)
torch.backends.cudnn.deterministic = True
torch.backends.cudnn.benchmark = False

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Global xy min/max from the training set, for smoothness-loss normalization.
flat_train_X = train_X.view(-1, train_X.shape[-1])  # [N*T, F]
coord_min = torch.tensor([flat_train_X[:, 0].min().item(), flat_train_X[:, 1].min().item()], device=device)
coord_max = torch.tensor([flat_train_X[:, 0].max().item(), flat_train_X[:, 1].max().item()], device=device)

input_size, hidden_size = 7, 64
input_steps, output_steps = 80, 2
model = Seq2SeqLSTM(input_size, hidden_size, input_steps, output_steps).to(device)
optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

train_model(model, train_dl, val_dl, optimizer, device,
            coord_min=coord_min, coord_max=coord_max)
```

## Step 7. Reload the best model and define evaluation helpers

A fresh session rebuilds everything from disk, the tensors, the scalers, the projection, and the best weights. The helpers invert the scaled residuals and positions back to meters, and haversine distances turn predicted lon/lat into errors a navigator can read.

```python
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

data = torch.load('datasets_npin.pt')
train_X, train_Y = data['train_X'], data['train_Y']
test_X, test_Y = data['test_X'], data['test_Y']
test_dl = DataLoader(TensorDataset(test_X, test_Y), batch_size=64)

feature_scaler = joblib.load("npinn_feature_scaler.pkl")
delta_scaler = joblib.load("npinn_delta_scaler.pkl")
with open("npinn_proj_params.json", "r") as f:
    proj = pyproj.Proj(**json.load(f))

best_model = Seq2SeqLSTM(input_size=train_X.shape[2], hidden_size=64,
                         input_steps=train_X.shape[1], output_steps=train_Y.shape[1]).to(device)
best_model.load_state_dict(torch.load("best_model_NPINN.pth", map_location=device))
best_model.eval()


def inverse_dxdy_np(dxdy_scaled, scaler):
    """Invert scaled (dx, dy) residuals back to meters."""
    dxdy_scaled = np.asarray(dxdy_scaled, dtype=float)
    if dxdy_scaled.ndim == 1:
        dxdy_scaled = dxdy_scaled[None, :]
    full_scaled = np.zeros((dxdy_scaled.shape[0], scaler.scale_.shape[0]))
    full_scaled[:, :2] = dxdy_scaled
    full = full_scaled * scaler.scale_ + scaler.center_
    return full[:, :2] if dxdy_scaled.shape[0] > 1 else full[0, :2]


def inverse_xy_only_np(xy_scaled, scaler):
    """Invert scaled x, y (first two columns of feature_scaler) to meters."""
    return xy_scaled * scaler.scale_[:2] + scaler.center_[:2]


def haversine(lon1, lat1, lon2, lat2):
    """Distance (m) between lon/lat points; handles arrays."""
    R = 6371000.0
    lon1, lat1, lon2, lat2 = map(np.radians, map(np.asarray, [lon1, lat1, lon2, lat2]))
    dlon, dlat = lon2 - lon1, lat2 - lat1
    a = np.sin(dlat/2.0)**2 + np.cos(lat1)*np.cos(lat2)*np.sin(dlon/2.0)**2
    return 2 * R * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def trajectory_length(lons, lats):
    lons, lats = np.asarray(lons, dtype=float), np.asarray(lats, dtype=float)
    if lons.size < 2 or not (np.isfinite(lons).all() and np.isfinite(lats).all()):
        return 0.0 if lons.size < 2 else float("nan")
    return np.sum(haversine(lons[:-1], lats[:-1], lons[1:], lats[1:]))
```

## Step 8. Evaluate on the held-out window

For each test batch the model predicts scaled residuals, which are inverted to meters, accumulated onto the last observed position, and projected back to lon/lat. Per-timestep haversine errors and trajectory-length differences summarize accuracy, and each true versus predicted pair is drawn on a map.

```python
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature


def evaluate_with_errors(model, test_dl, proj, feature_scaler, delta_scaler,
                         device, dup_tol=1e-4, plot_map=True):
    """Evaluate trajectory predictions, report errors in meters, optionally plot."""
    model.eval()
    errors_all, length_diffs = [], []
    all_real, all_pred = [], []

    with torch.no_grad():
        for xb, yb in test_dl:
            xb, yb = xb.to(device), yb.to(device)
            pred = model(xb, teacher_forcing_ratio=0.0)  # [B, T_out, 2]

            # First sample of the batch.
            input_seq = xb[0].cpu().numpy()
            real_seq = yb[0].cpu().numpy()
            pred_seq = pred[0].cpu().numpy()

            # Invert residuals to meters, then accumulate from the last observed position.
            pred_resid_m = inverse_dxdy_np(pred_seq[:, :2], delta_scaler)
            real_resid_m = inverse_dxdy_np(real_seq[:, :2], delta_scaler)
            last_obs_xy_m = inverse_xy_only_np(input_seq[-1, :2], feature_scaler)
            pred_xy_m = np.cumsum(pred_resid_m, axis=0) + last_obs_xy_m
            real_xy_m = np.cumsum(real_resid_m, axis=0) + last_obs_xy_m

            # Remove first target if it duplicates the last input, then align.
            if np.allclose(real_resid_m[0], 0, atol=dup_tol):
                real_xy_m, pred_xy_m = real_xy_m[1:], pred_xy_m[1:]
            min_len = min(len(pred_xy_m), len(real_xy_m))
            pred_xy_m, real_xy_m = pred_xy_m[:min_len], real_xy_m[:min_len]

            lon_real, lat_real = proj(real_xy_m[:, 0], real_xy_m[:, 1], inverse=True)
            lon_pred, lat_pred = proj(pred_xy_m[:, 0], pred_xy_m[:, 1], inverse=True)
            all_real.append((lon_real, lat_real))
            all_pred.append((lon_pred, lat_pred))

            errors_all.append(haversine(lon_real, lat_real, lon_pred, lat_pred))
            real_len = trajectory_length(lon_real, lat_real)
            pred_len = trajectory_length(lon_pred, lat_pred)
            length_diffs.append(abs(real_len - pred_len))
            print(f"Trajectory length (true): {real_len:.2f} m | pred: {pred_len:.2f} m | diff: {abs(real_len - pred_len):.2f} m")

    # Pad to a common horizon, then summarize.
    max_len = max(len(e) for e in errors_all)
    errors_padded = np.full((len(errors_all), max_len), np.nan)
    for i, e in enumerate(errors_all):
        errors_padded[i, :len(e)] = e

    mean_per_t = np.nanmean(errors_padded, axis=0)
    print("\n=== Summary (meters) ===")
    for t, v in enumerate(mean_per_t):
        if not np.isnan(v):
            print(f"t={t} mean error: {v:.2f} m")
    print(f"Mean over horizon: {np.nanmean(errors_padded):.2f} m | Median: {np.nanmedian(errors_padded):.2f} m")
    print(f"Mean trajectory length diff: {np.mean(length_diffs):.2f} m | Median: {np.median(length_diffs):.2f} m")

    if plot_map:
        for idx, ((lon_r, lat_r), (lon_p, lat_p)) in enumerate(zip(all_real, all_pred)):
            plt.figure(figsize=(10, 8))
            ax = plt.axes(projection=ccrs.PlateCarree())
            ax.add_feature(cfeature.LAND)
            ax.add_feature(cfeature.COASTLINE)
            ax.add_feature(cfeature.BORDERS, linestyle=':')
            ax.plot(lon_r, lat_r, color='green', linewidth=2, label="True")
            ax.plot(lon_p, lat_p, color='red', linestyle='--', linewidth=2, label="Predicted")
            ax.legend()
            ax.set_title(f"Trajectory {idx+1}: True vs Predicted")
            plt.show()


evaluate_with_errors(best_model, test_dl, proj, feature_scaler, delta_scaler,
                     device, plot_map=True)
```

## Results

Calling `evaluate_with_errors` on the held-out August 2018 window walks the test set trajectory by trajectory, printing the true and predicted length in meters for each one and rendering a map of the two paths.

Trajectory 2 covers 521.39 m in the ground truth and 508.66 m in the prediction, a difference of 12.73 m. In the figure below, the predicted path tracks the true path closely and stays roughly parallel to it, offset by a small, consistent margin rather than drifting away over time. The model underestimates the total path length by about 2.4%, a small error, and the smoothness of the predicted line is exactly what the kinematic penalty in the loss is meant to produce.

<figure><img src="../.gitbook/assets/image (1).png" alt=""><figcaption>Predicted (red) vs. true (green) vessel trajectory 2, Gulf of St. Lawrence test window, August 2018.</figcaption></figure>

```
Trajectory length (true): 521.39 m | pred: 508.66 m | diff: 12.73 m
```

Trajectory 5 runs the other way. The true length is 188.76 m against a predicted 206.01 m, overestimating the distance by about 9%. The path is still smooth and follows the right general direction, but the larger relative error on a shorter trajectory shows the model has more trouble scaling step lengths correctly when there is less distance for it to work with.

<figure><img src="../.gitbook/assets/image (2).png" alt=""><figcaption>Predicted (red) vs. true (green) vessel trajectory 5, Gulf of St. Lawrence test window, August 2018.</figcaption></figure>

```
Trajectory length (true): 188.76 m | pred: 206.01 m | diff: 17.25 m
```

Aggregated across the full test set, the mean per-timestep error is 45.03 m at the first predicted step and climbs to 80.80 m at the second, the usual compounding pattern for a residual model. Over the full two-step horizon the mean error is 62.92 m and the median is 61.72 m, close enough that a handful of outlier trajectories is not dragging the distribution around. Trajectory length holds up better than pointwise position, with a mean length difference of 11.82 m and a median of 12.73 m, under 3% relative error for most trajectories. Errors grow smoothly with the horizon rather than in erratic jumps, which is the signature the NPINN penalty is supposed to leave behind, though the two-step horizon tested here is short enough that longer horizons and a larger test population deserve their own validation.

## Takeaway

* The kinematic penalty is cheap to add and leaves a visible signature. Errors grow smoothly with the horizon, 45.03 m at the first step and 80.80 m at the second, instead of jumping erratically.
* Fit scalers on the training window only, reuse them on the test window, and invert them before reporting, so every error reads in meters rather than scaled units.
* The pipeline assumes one UTM zone (zone 20 here) and dense reporters (a 100-ping minimum), so swap the projection and revalidate before trusting it on wide regions, sparse vessels, or horizons past two steps.
* Every vessel is forecast from its own history alone, so converging traffic is invisible to the model.

Next, [TGNs with TorchGeometric](tgns-with-torchgeometric.md) models traffic as a temporal graph, so the model learns from the relational structure of traffic rather than one ship at a time.
