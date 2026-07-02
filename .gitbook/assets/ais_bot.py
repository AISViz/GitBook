# ais_agent_app.py

import os
import io
import json
import base64
import tempfile
import traceback
from datetime import timedelta
from typing import Optional, Dict, Any, List, Iterable, Tuple

import numpy as np
import pandas as pd


os.environ["GOOGLE_API_KEY"] = os.getenv("GOOGLE_API_KEY", "")

# Optional imports with guards
def _try_import(name, alias=None):
    try:
        module = __import__(name) if alias is None else __import__(alias, fromlist=[name])
        return module
    except Exception:
        return None

gr = _try_import("gradio")
if gr is None:
    raise RuntimeError("gradio is required. pip install gradio")

# AISDB modules (optional but many features depend on these)
aisdb = _try_import("aisdb")
TrackGen = None
split_timedelta = None
Discretizer = None
WeatherDataStore = None
encodegreatcircledistance = None
try:
    if aisdb is not None:
        from aisdb.track_gen import TrackGen, split_timedelta  # type: ignore
        from aisdb.discretize.h3 import Discretizer  # type: ignore
        from aisdb.weather.data_store import WeatherDataStore  # type: ignore
        from aisdb.denoising_encoder import encode_greatcircledistance as encodegreatcircledistance  # type: ignore
except Exception:
    pass

h3 = _try_import("h3")
rasterio = _try_import("rasterio")
if rasterio:
    try:
        from rasterio.transform import rowcol  # type: ignore
    except Exception:
        rowcol = None

matplotlib = _try_import("matplotlib")
if matplotlib:
    try:
        matplotlib.use("Agg")
    except Exception:
        pass
plt = None
try:
    import matplotlib.pyplot as plt  # type: ignore
except Exception:
    plt = None

ccrs = None
try:
    import cartopy.crs as ccrs  # type: ignore
except Exception:
    ccrs = None

plotly_express = _try_import("plotly.express", "plotly")
go = None
try:
    import plotly.graph_objects as go  # type: ignore
except Exception:
    go = None

# Google / LangChain (optional)
ChatGoogleGenerativeAI = None
genai = None
try:
    from langchain_google_genai import ChatGoogleGenerativeAI  # type: ignore
except Exception:
    ChatGoogleGenerativeAI = None
try:
    import google.generativeai as genai  # type: ignore
except Exception:
    genai = None

# Capability flags
HAS_AISDB = TrackGen is not None and Discretizer is not None
HAS_ENCODER = encodegreatcircledistance is not None
HAS_WEATHER = WeatherDataStore is not None
HAS_MPL = plt is not None
HAS_CARTOPY = ccrs is not None
HAS_PLOTLY = go is not None
HAS_LC_GOOGLE = ChatGoogleGenerativeAI is not None
HAS_GOOGLE_SDK = genai is not None

# ---------- Helpers ----------
def ensure_time_parsed(df: pd.DataFrame, timecol: str = "time") -> pd.DataFrame:
    if timecol not in df.columns:
        raise ValueError("Missing time column")
    s = df[timecol]
    try:
        if pd.api.types.is_integer_dtype(s) or pd.api.types.is_float_dtype(s):
            df[timecol] = pd.to_datetime(s, unit="s", utc=True)
        else:
            df[timecol] = pd.to_datetime(s, utc=True, errors="coerce")
    except Exception:
        df[timecol] = pd.to_datetime(s, utc=True, errors="coerce")
    return df


def save_df_to_temp_csv(df: pd.DataFrame) -> str:
    tmpdir = os.environ.get("GRADIO_TEMP_DIR", tempfile.gettempdir())
    os.makedirs(tmpdir, exist_ok=True)
    out = tempfile.mktemp(suffix=".csv", dir=tmpdir)
    df.to_csv(out, index=False)
    return out


def split_tracks_by_time(df: pd.DataFrame, gap_minutes: int) -> List[pd.DataFrame]:
    df = df.sort_values(["mmsi", "time"]).reset_index(drop=True)
    segments: List[pd.DataFrame] = []
    gap = timedelta(minutes=int(gap_minutes))
    for _, group in df.groupby("mmsi", sort=True):
        times = list(group["time"])
        idxs = list(group.index)
        if not idxs:
            continue
        cur = [idxs[0]]
        prevt = times[0]
        for idx, t in zip(idxs[1:], times[1:]):
            if t - prevt > gap:
                segments.append(group.loc[cur].copy().reset_index(drop=True))
                cur = [idx]
            else:
                cur.append(idx)
            prevt = t
        segments.append(group.loc[cur].copy().reset_index(drop=True))
    return segments


def discretize_h3_dfsegment(dfsegment: pd.DataFrame, resolution: int = 6, latcol="lat", loncol="lon") -> List[str]:
    out: List[str] = []
    if h3 is not None:
        for _, r in dfsegment.iterrows():
            try:
                out.append(h3.geo_to_h3(float(r[latcol]), float(r[loncol]), resolution))  # type: ignore
            except Exception:
                out.append(f"{r[latcol]},{r[loncol]}")
    else:
        for _, r in dfsegment.iterrows():
            out.append(f"{r[latcol]},{r[loncol]}")
    return out


def detect_stops_from_segment(dfsegment: pd.DataFrame, sogcol="sog", speedthreshold=0.5, minstopminutes=30) -> List[Dict[str, Any]]:
    stops: List[Dict[str, Any]] = []
    times = list(dfsegment["time"])
    sogs = list(dfsegment[sogcol]) if sogcol in dfsegment.columns else [0] * len(dfsegment)
    current: List[Tuple[pd.Timestamp, Any]] = []
    h3s = discretize_h3_dfsegment(dfsegment)
    for t, sog, h3v in zip(times, sogs, h3s):
        if pd.isna(sog) or sog <= speedthreshold:
            current.append((t, h3v))
        else:
            if current:
                firstt, lastt = current[0][0], current[-1][0]
                dur = (lastt - firstt).total_seconds() / 60.0
                if dur >= minstopminutes:
                    stops.append({
                        "mmsi": int(dfsegment["mmsi"].iloc[0]) if "mmsi" in dfsegment.columns else -1,
                        "starttime": int(firstt.timestamp()),
                        "endtime": int(lastt.timestamp()),
                        "duration_min": dur,
                        "h3index": current[0][1],
                        "shiptype": dfsegment["shiptype"].iloc[0] if "shiptype" in dfsegment.columns else "Unknown",
                    })
            current = []
    if current:
        firstt, lastt = current[0][0], current[-1][0]
        dur = (lastt - firstt).total_seconds() / 60.0
        if dur >= minstopminutes:
            stops.append({
                "mmsi": int(dfsegment["mmsi"].iloc[0]) if "mmsi" in dfsegment.columns else -1,
                "starttime": int(firstt.timestamp()),
                "endtime": int(lastt.timestamp()),
                "duration_min": dur,
                "h3index": current[0][1],
                "shiptype": dfsegment["shiptype"].iloc[0] if "shiptype" in dfsegment.columns else "Unknown",
            })
    return stops


def parse_shortnames_from_csvish(s: str) -> Optional[List[str]]:
    if not s or not isinstance(s, str):
        return None
    txt = s.strip()
    if not txt:
        return None
    if ("{" not in txt and "}" not in txt) and ("," in txt) and ("\n" not in txt):
        vals = [x.strip() for x in txt.split(",") if x.strip()]
        return vals if vals else None
    try:
        from io import StringIO
        dfcsv = pd.read_csv(StringIO(txt))
        if dfcsv.shape[1] == 1:
            col = dfcsv.columns[0]
            vals = [str(v).strip() for v in dfcsv[col].dropna().astype(str).tolist() if str(v).strip()]
            return vals if vals else None
        if "shortnames" in dfcsv.columns:
            vals = [str(v).strip() for v in dfcsv["shortnames"].dropna().astype(str).tolist() if str(v).strip()]
            return vals if vals else None
    except Exception:
        pass
    return None


def dfto_aisdb_trackgen(df: pd.DataFrame) -> Iterable[Dict[str, Any]]:
    """
    Yield grouped rows shaped like AISDB row-track dictionaries suitable for downstream utilities.
    """
    required = {"mmsi", "time", "lon", "lat"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    dfl = df.copy()

    # Normalize time to timezone-aware UTC datetime
    if not pd.api.types.is_datetime64_any_dtype(dfl["time"]):
        dfl["time"] = pd.to_datetime(dfl["time"], utc=True, errors="coerce")
    else:
        ts = pd.to_datetime(dfl["time"], utc=True, errors="coerce")
        dfl["time"] = ts

    # Group by MMSI after sorting by mmsi, time
    dfl = dfl.sort_values(["mmsi", "time"], kind="mergesort")
    g = dfl.groupby("mmsi", sort=True, dropna=False)

    def gen():
        for mmsi, group in g:
            tsutc = group["time"]
            if getattr(tsutc.dt, "tz", None) is not None:
                tsutc = tsutc.dt.tz_convert("UTC")
            else:
                tsutc = tsutc.dt.tz_localize("UTC")
            # view int64 seconds since epoch
            tepoch = (tsutc.view("int64") // 10**9).astype("uint32").to_numpy()
            lat = pd.to_numeric(group["lat"], errors="coerce").astype("float32").to_numpy()
            lon = pd.to_numeric(group["lon"], errors="coerce").astype("float32").to_numpy()
            try:
                mmsi_int = int(mmsi) if mmsi is not None else -1
            except Exception:
                mmsi_int = -1

            yield {
                "mmsi": mmsi_int,
                "lat": lat,
                "lon": lon,
                "time": tepoch,
                "static": {"mmsi": mmsi_int},
                "dynamic": {"lat": lat, "lon": lon, "time": tepoch},
            }

    return gen()


def aisdb_split_by_timedelta(df: pd.DataFrame, gap: timedelta):
    if not HAS_AISDB or split_timedelta is None:
        raise RuntimeError("AISDB split_timedelta not available. Install aisdb.")
    rowtracks = dfto_aisdb_trackgen(df)
    return split_timedelta(rowtracks, gap)


def aisdb_encode_great_circle_distance(segments, distance_threshold: float, speed_threshold: float):
    if not HAS_ENCODER:
        raise RuntimeError("AISDB encode_greatcircledistance not available.")
    return encodegreatcircledistance(segments, distance_threshold=distance_threshold, speed_threshold=speed_threshold)


def aisdb_discretize_indexes(df: pd.DataFrame, resolution: int = 6) -> Optional[pd.DataFrame]:
    if not HAS_AISDB or Discretizer is not None is False:
        raise RuntimeError("AISDB Discretizer not available. Install aisdb.")
    rowtracks = dfto_aisdb_trackgen(df)
    des = Discretizer(resolution=resolution)
    rows = []
    for t in des.yield_tracks_discretized_by_indexes(rowtracks):
        # Expected keys include "time","lat","lon","h3_index" (aisdb structure)
        if not all(k in t for k in ("time", "lat", "lon", "h3_index")):
            continue
        n = min(len(t["time"]), len(t["lat"]), len(t["lon"]), len(t["h3_index"]))
        mmsi_val = t.get("mmsi", -1)
        for i in range(n):
            h3v = t["h3_index"][i]
            try:
                h3v = str(int(h3v))
            except Exception:
                h3v = str(h3v)
            rows.append({
                "mmsi": int(mmsi_val) if mmsi_val is not None else -1,
                "time": pd.to_datetime(int(t["time"][i]), unit="s", utc=True),
                "lat": float(t["lat"][i]),
                "lon": float(t["lon"][i]),
                "h3index": h3v,
            })
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["mmsi","time","lat","lon","h3index"])


# ---------- Bathymetry ----------
class BathymetryClientLocal:
    def __init__(self, rasterpath: str):
        if rasterio is None:
            raise RuntimeError("rasterio required. pip install rasterio")
        if not os.path.exists(rasterpath):
            raise FileNotFoundError(f"Bathymetry raster not found: {rasterpath}")
        self.src = rasterio.open(rasterpath)

    def query(self, lats, lons):
        src = self.src
        coords = list(zip(lons, lats))
        vals = []
        try:
            for val in src.sample(coords):
                v = float(val[0]) if val.size > 0 else None
                if v is None or (isinstance(v, float) and np.isnan(v)):
                    v = None
                vals.append(v)
        except Exception:
            # Fallback windowed read
            for lon, lat in coords:
                try:
                    if rowcol is None:
                        vals.append(None)
                        continue
                    r, c = rowcol(src.transform, lon, lat)  # type: ignore
                    windowval = src.read(1, window=((r, r+1), (c, c+1)), boundless=True, masked=True)
                    if windowval is None or windowval.size == 0:
                        vals.append(None)
                    else:
                        vv = float(windowval.flatten()[0])
                        vals.append(None if np.isnan(vv) else vv)
                except Exception:
                    vals.append(None)
        return np.array(vals)

    def close(self):
        try:
            self.src.close()
        except Exception:
            pass


# ---------- Plotting ----------
def plot_tracks_core(df: pd.DataFrame, usecartopy: bool, coastlines: bool, figsize=(12, 8)):
    if not HAS_MPL:
        raise RuntimeError("matplotlib not available.")
    mmsis = df["mmsi"].unique().tolist() if "mmsi" in df.columns else [-1]
    cmap = plt.get_cmap("tab20")
    colormap = {m: cmap(i % 20) for i, m in enumerate(mmsis)}
    if usecartopy and HAS_CARTOPY:
        fig = plt.figure(figsize=figsize)
        ax = plt.axes(projection=ccrs.Mercator())
        datacrs = ccrs.PlateCarree()
        if coastlines:
            ax.coastlines()
        if "lon" in df.columns and "lat" in df.columns and not df.empty:
            lonmin, lonmax = float(df["lon"].min()), float(df["lon"].max())
            latmin, latmax = float(df["lat"].min()), float(df["lat"].max())
            try:
                ax.set_extent((lonmin, lonmax, latmin, latmax), crs=datacrs)
            except Exception:
                pass
        for mmsi, g in df.groupby("mmsi", sort=True):
            ax.plot(g["lon"].to_numpy(), g["lat"].to_numpy(),
                    transform=datacrs, color=colormap.get(mmsi, "C0"), linewidth=1.5, alpha=0.9)
        ax.set_title("AIS Tracks Visualization")
        fig.tight_layout()
        return fig
    else:
        fig, ax = plt.subplots(figsize=figsize)
        for mmsi, g in df.groupby("mmsi", sort=True):
            ax.plot(g["lon"].to_numpy(), g["lat"].to_numpy(),
                    color=colormap.get(mmsi, "C0"), linewidth=1.5, alpha=0.9)
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.set_title("AIS Tracks Visualization (no cartopy)")
        fig.tight_layout()
        return fig


def render_plot_to_files(fig, wantpng: bool, wantpdf: bool):
    out = {"png": None, "pdf": None}
    tmpdir = os.environ.get("GRADIO_TEMP_DIR", tempfile.gettempdir())
    os.makedirs(tmpdir, exist_ok=True)
    if wantpng:
        pngpath = tempfile.mktemp(suffix=".png", dir=tmpdir)
        fig.savefig(pngpath, dpi=180, bbox_inches="tight")
        out["png"] = pngpath
    if wantpdf:
        pdfpath = tempfile.mktemp(suffix=".pdf", dir=tmpdir)
        fig.savefig(pdfpath, dpi=180, bbox_inches="tight")
        out["pdf"] = pdfpath
    plt.close(fig)
    return out


def plotly_tracks_osm(df: pd.DataFrame, linemode: bool = True):
    if not HAS_PLOTLY:
        raise RuntimeError("plotly not available. pip install plotly")
    if df.empty:
        raise RuntimeError("No rows to plot after removing missing lat/lon.")
    fig = go.Figure()
    for mmsi, g in df.sort_values(["mmsi", "time"]).groupby("mmsi", sort=True):
        lat = g["lat"].astype(float).tolist()
        lon = g["lon"].astype(float).tolist()
        hover = []
        hastime = ("time" in g.columns)
        for _, r in g.iterrows():
            ht = f"MMSI {int(r['mmsi'])}" if pd.notna(r.get("mmsi", None)) else "-1"
            if hastime and pd.notna(r.get("time", None)):
                try:
                    ht += f"<br>time {pd.to_datetime(r['time']).isoformat()}"
                except Exception:
                    pass
            if "sog" in r and pd.notna(r["sog"]):
                ht += f"<br>sog {r['sog']}"
            hover.append(ht)
        if linemode:
            fig.add_trace(go.Scattermapbox(
                lat=lat, lon=lon, mode="lines+markers",
                line=dict(width=2), marker=dict(size=6),
                name=str(mmsi), text=hover, hoverinfo="text"
            ))
        else:
            fig.add_trace(go.Scattermapbox(
                lat=lat, lon=lon, mode="markers",
                marker=dict(size=6),
                name=str(mmsi), text=hover, hoverinfo="text"
            ))
    lonmin, lonmax = float(df["lon"].min()), float(df["lon"].max())
    latmin, latmax = float(df["lat"].min()), float(df["lat"].max())
    centerlat = (latmin + latmax) / 2.0
    centerlon = (lonmin + lonmax) / 2.0
    fig.update_layout(
        mapbox_style="open-street-map",
        mapbox=dict(center=dict(lat=centerlat, lon=centerlon), zoom=3),
        margin=dict(l=0, r=0, t=40, b=0),
        title="AIS Tracks Plotly OSM"
    )
    return fig


def save_plotly_html(fig) -> str:
    tmpdir = os.environ.get("GRADIO_TEMP_DIR", tempfile.gettempdir())
    os.makedirs(tmpdir, exist_ok=True)
    outpath = tempfile.mktemp(suffix=".html", dir=tmpdir)
    fig.write_html(outpath, include_plotlyjs=True, full_html=True)
    return outpath


# ---------- Agent ----------
class AISAgent:
    def __init__(self):
        self.df: Optional[pd.DataFrame] = None
        self.last_output_csv: Optional[str] = None
        self.df_desc_json: Optional[str] = None
        self.df_schema_json: Optional[str] = None
        self.llm = None
        if HAS_LC_GOOGLE and os.getenv("GOOGLE_API_KEY"):
            try:
                self.llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite", temperature=0.0)
            except Exception:
                self.llm = None
        # store latest plot paths and base64 for Gemini
        self.last_png_path: Optional[str] = None
        self.last_pdf_path: Optional[str] = None
        self.last_plot_b64: Optional[str] = None

    def load_csv(self, filepath: str) -> str:
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Uploaded file not found: {filepath}")
        df = pd.read_csv(filepath)
        cols = {c.lower(): c for c in df.columns}

        def pick(*names):
            for n in names:
                if n in cols:
                    return cols[n]
            return None

        tcol = pick("time", "timestamp", "datetime", "ts")
        latc = pick("lat", "latitude")
        lonc = pick("lon", "longitude", "lng")
        mmsic = pick("mmsi")
        sogc = pick("sog", "speed", "speedoverground")
        if tcol is None or latc is None or lonc is None:
            raise ValueError("CSV must contain time and lat/lon columns.")
        df = df.rename(columns={tcol: "time", latc: "lat", lonc: "lon"})
        if mmsic:
            df = df.rename(columns={mmsic: "mmsi"})
        else:
            df["mmsi"] = -1
        if sogc:
            df = df.rename(columns={sogc: "sog"})
        else:
            df["sog"] = np.nan
        df = ensure_time_parsed(df, "time")
        if df["time"].isna().any():
            raise ValueError("Some time values could not be parsed.")

        self.df = df.sort_values(["mmsi", "time"]).reset_index(drop=True)

        # dataset descriptions
        try:
            desc = self.df.describe(include="all", datetime_is_numeric=True)
            desc = desc.dropna(how="all", axis=0).dropna(how="all", axis=1)
            if desc.empty:
                schema = {
                    "columns": [{"name": str(col), "dtype": str(self.df[col].dtype), "nonnull": int(self.df[col].notna().sum())}
                                for col in self.df.columns],
                    "rows": int(len(self.df)),
                }
                self.df_desc_json = json.dumps(schema)
                self.df_schema_json = self.df_desc_json
            else:
                self.df_desc_json = desc.to_json(orient="table")
                schema = {
                    "columns": [{"name": str(col), "dtype": str(self.df[col].dtype), "nonnull": int(self.df[col].notna().sum())}
                                for col in self.df.columns],
                    "rows": int(len(self.df)),
                }
                self.df_schema_json = json.dumps(schema)
        except Exception:
            schema = {
                "columns": [{"name": str(col), "dtype": str(self.df[col].dtype), "nonnull": int(self.df[col].notna().sum())}
                            for col in self.df.columns],
                "rows": int(len(self.df)),
            }
            self.df_desc_json = json.dumps(schema)
            self.df_schema_json = self.df_desc_json
        return f"Loaded CSV with {len(self.df)} rows and columns {list(self.df.columns)}"

    def process_steps(self,
                      steps: List[str],
                      gapminutes: int,
                      encodedistancem: float,
                      encodespeedkn: float,
                      h3res: int,
                      rasterpath: Optional[str],
                      weathercfg: Optional[Dict[str, Any]],
                      timesplitdays: Optional[float] = None,
                      distancesplitm: Optional[float] = None,
                      speedsplitkn: Optional[float] = None) -> str:
        if self.df is None:
            return "No CSV loaded. Upload CSV first."
        try:
            dfcur = self.df.copy()

            user_timedelta = timedelta(days=float(timesplitdays)) if timesplitdays is not None else None
            user_distance_split = float(distancesplitm) if distancesplitm is not None else None
            user_speed_split = float(speedsplitkn) if speedsplitkn is not None else None

            segiter = None
            if ("Split by time" in steps):
                if HAS_AISDB and split_timedelta is not None:
                    splittd = user_timedelta if user_timedelta is not None else timedelta(minutes=gapminutes)
                    segiter = aisdb_split_by_timedelta(dfcur, splittd)
                else:
                    # local splitter, assign segmentid
                    segs = split_tracks_by_time(dfcur, gapminutes if user_timedelta is None else int(user_timedelta.total_seconds() / 60))
                    rows = []
                    for sid, s in enumerate(segs):
                        s2 = s.copy()
                        s2["segmentid"] = sid
                        rows.append(s2)
                    dfcur = pd.concat(rows, ignore_index=True) if rows else dfcur

            if ("Encode track" in steps):
                if not HAS_AISDB or not HAS_ENCODER:
                    raise RuntimeError("Encode track requires aisdb with denoising encoder installed.")
                if segiter is None:
                    splittd = user_timedelta if user_timedelta is not None else timedelta(minutes=gapminutes)
                    segiter = aisdb_split_by_timedelta(dfcur, splittd)
                encdist = user_distance_split if user_distance_split is not None else float(encodedistancem)
                encspeed = user_speed_split if user_speed_split is not None else float(encodespeedkn)
                segiter = aisdb_encode_great_circle_distance(segiter, encdist, encspeed)
                if segiter is not None:
                    rows = []
                    segid = 0
                    for t in segiter:
                        if not all(k in t for k in ("time", "lat", "lon")):
                            continue
                        n = len(t["time"])
                        for i in range(n):
                            rows.append({
                                "segmentid": segid,
                                "mmsi": int(t.get("mmsi", -1)),
                                "time": pd.to_datetime(int(t["time"][i]), unit="s", utc=True),
                                "lat": float(t["lat"][i]),
                                "lon": float(t["lon"][i]),
                            })
                        segid += 1
                    dfcur = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["segmentid","mmsi","time","lat","lon"])

            if ("Discretize H3" in steps):
                if not HAS_AISDB:
                    raise RuntimeError("Discretize H3 requires aisdb installed.")
                dfdisc = aisdb_discretize_indexes(dfcur, resolution=int(h3res))
                if dfdisc is not None and not dfdisc.empty:
                    # use consistent column name 'h3index'
                    dfcur = dfcur.merge(dfdisc[["mmsi", "time", "h3index"]].drop_duplicates(),
                                        on=["mmsi","time"], how="left")

            if ("Detect stops" in steps):
                groupkeys = ["mmsi","segmentid"] if "segmentid" in dfcur.columns else ["mmsi"]
                stops = []
                for _, g in dfcur.sort_values(groupkeys + ["time"]).groupby(groupkeys, sort=True):
                    stops.extend(detect_stops_from_segment(g, sogcol="sog"))
                dfstops = pd.DataFrame(stops)
                if not dfstops.empty:
                    stopcounts = dfstops.groupby("mmsi").size().reset_index(name="stop_events")
                    dfcur = dfcur.merge(stopcounts, on="mmsi", how="left")

            if ("Add bathymetry" in steps):
                if rasterio is None:
                    raise RuntimeError("rasterio not installed; cannot add bathymetry.")
                if not rasterpath:
                    raise RuntimeError("Bathymetry requires rasterpath.")
                client = BathymetryClientLocal(rasterpath)
                depths = client.query(dfcur["lat"].values, dfcur["lon"].values)
                client.close()
                dfcur["depth_m"] = depths

            if ("Add weather" in steps):
                if not HAS_WEATHER:
                    raise RuntimeError("AISdb WeatherDataStore unavailable")
                if dfcur.empty or "time" not in dfcur.columns:
                    raise RuntimeError("Cannot infer weather time range: missing 'time' or no rows.")
                tsall = dfcur["time"]
                if not pd.api.types.is_datetime64_any_dtype(tsall):
                    tsall = pd.to_datetime(tsall, errors="coerce", utc=True)
                if getattr(tsall.dt, "tz", None) is not None:
                    tsallutc = tsall.dt.tz_convert("UTC")
                else:
                    tsallutc = tsall.dt.tz_localize("UTC")
                computed_start = tsallutc.min() if len(tsallutc) else None
                computed_end = tsallutc.max() if len(tsallutc) else None
                if dfcur.empty or not {"lat","lon"}.issubset(dfcur.columns):
                    raise RuntimeError("Cannot infer weather area: missing lat/lon or no rows.")
                latmin = float(pd.to_numeric(dfcur["lat"], errors="coerce").min())
                latmax = float(pd.to_numeric(dfcur["lat"], errors="coerce").max())
                lonmin = float(pd.to_numeric(dfcur["lon"], errors="coerce").min())
                lonmax = float(pd.to_numeric(dfcur["lon"], errors="coerce").max())
                computed_area = (latmax, lonmin, latmin, lonmax)  # north, west, south, east

                wc = weathercfg or {}
                shortnames = wc.get("shortnames", ["10u", "10v"])
                weatherpath = wc.get("weather_data_path", None)
                downloadfromcds = wc.get("download_from_cds", True)
                start = pd.to_datetime(wc.get("start", computed_start), utc=True)
                end = pd.to_datetime(wc.get("end", computed_end), utc=True)
                area = wc.get("area", computed_area)
                if start is None or end is None:
                    raise RuntimeError("Cannot infer weather time range after parsing.")

                store = WeatherDataStore(shortnames=shortnames, start=start, end=end,
                                         weather_data_path=weatherpath, download_from_cds=downloadfromcds, area=area)

                def tracksgen():
                    for mmsi, g in dfcur.groupby("mmsi", sort=True):
                        ts = g["time"]
                        if not pd.api.types.is_datetime64_any_dtype(ts):
                            ts = pd.to_datetime(ts, errors="coerce", utc=True)
                        if getattr(ts.dt, "tz", None) is not None:
                            tsutc = ts.dt.tz_convert("UTC")
                        else:
                            tsutc = ts.dt.tz_localize("UTC")
                        epoch = (tsutc.view("int64") // 10**9).astype("int64").tolist()
                        yield {"mmsi": int(mmsi) if mmsi is not None else -1,
                               "lat": g["lat"].tolist(), "lon": g["lon"].tolist(), "time": epoch}

                tracks_with_weather = store.yield_tracks_with_weather(tracksgen())
                rows = []
                for t in tracks_with_weather:
                    times = t["time"]
                    lats = t["lat"]
                    lons = t["lon"]
                    w = t.get("weather_data", {})
                    for i in range(len(times)):
                        row = {
                            "time": pd.to_datetime(int(times[i]), unit="s", utc=True),
                            "lat": lats[i],
                            "lon": lons[i],
                        }
                        for k, arr in w.items():
                            row[k] = arr[i] if i < len(arr) else None
                        rows.append(row)
                store.close()
                dfw = pd.DataFrame(rows)
                if not dfw.empty:
                    dfcur = dfcur.merge(dfw, on=["time", "lat", "lon"], how="left")

            path = save_df_to_temp_csv(dfcur)
            self.last_output_csv = path
            schema = {
                "columns": [{"name": str(col), "dtype": str(dfcur[col].dtype), "nonnull": int(dfcur[col].notna().sum())}
                            for col in dfcur.columns],
                "rows": int(len(dfcur)),
            }
            self.df_schema_json = json.dumps(schema)

            preview_cols = [c for c in ["mmsi","segmentid","time","lat","lon","h3index","depth_m"] if c in dfcur.columns]
            if preview_cols:
                headtxt = dfcur[preview_cols].head(12).to_string(index=False)
            else:
                headtxt = dfcur.head(12).to_string(index=False)
            return f"Processed {len(dfcur)} rows. Saved: {path}\n\n{headtxt}"
        except Exception as e:
            return f"Error: {e}\n{traceback.format_exc()}"

    def plot_tracks(self, enableplot: bool, usecartopy: bool, addcoastlines: bool,
                    exportpng: bool, exportpdf: bool) -> Tuple[Optional[str], Optional[str], str, Optional[str]]:
        # Returns: png_path, pdf_path, status, base64_png
        if not enableplot:
            return None, None, "Plotting disabled by checkbox.", None
        if self.df is None:
            return None, None, "No CSV loaded. Upload CSV first.", None
        if not HAS_MPL:
            return None, None, "matplotlib not available; install matplotlib.", None
        try:
            if self.last_output_csv and os.path.exists(self.last_output_csv):
                dfplot = pd.read_csv(self.last_output_csv)
                if "time" in dfplot.columns:
                    try:
                        dfplot["time"] = pd.to_datetime(dfplot["time"], utc=True, errors="coerce")
                    except Exception:
                        pass
            else:
                dfplot = self.df.copy()
            for c in ["mmsi","lat","lon"]:
                if c not in dfplot.columns:
                    return None, None, f"Missing column for plotting: {c}", None
            dfplot = dfplot.dropna(subset=["lat","lon"])
            if dfplot.empty:
                return None, None, "No rows to plot after removing missing lat/lon.", None

            fig = plot_tracks_core(dfplot, usecartopy=usecartopy, coastlines=addcoastlines)
            files = render_plot_to_files(fig, wantpng=exportpng, wantpdf=exportpdf)
            imagepath = files["png"]
            pdfpath = files["pdf"]

            b64_png = None
            if imagepath and os.path.exists(imagepath):
                with open(imagepath, "rb") as f:
                    b64_png = base64.b64encode(f.read()).decode("utf-8")

            self.last_png_path = imagepath
            self.last_pdf_path = pdfpath
            self.last_plot_b64 = b64_png

            status = f"Rendered plot. PNG={bool(imagepath)}, PDF={bool(pdfpath)}"
            return imagepath, pdfpath, status, b64_png
        except Exception as e:
            return None, None, f"Plot error: {e}", None

    def plot_tracks_plotly(self, enableplotly: bool, linemode: bool, exporthtml: bool):
        if not enableplotly:
            return None, None, "Plotly disabled."
        if not HAS_PLOTLY:
            return None, None, "plotly not available. pip install plotly"
        if self.df is None:
            return None, None, "No CSV loaded. Upload CSV first."
        try:
            if self.last_output_csv and os.path.exists(self.last_output_csv):
                dfplot = pd.read_csv(self.last_output_csv)
            else:
                dfplot = self.df.copy()
            for c in ["mmsi","lat","lon"]:
                if c not in dfplot.columns:
                    return None, None, f"Missing column for plotting: {c}"
            if "time" in dfplot.columns:
                try:
                    dfplot["time"] = pd.to_datetime(dfplot["time"], utc=True, errors="coerce")
                except Exception:
                    pass
            dfplot = dfplot.dropna(subset=["lat","lon"])
            if dfplot.empty:
                return None, None, "No rows to plot after removing missing lat/lon."
            fig = plotly_tracks_osm(dfplot, linemode=linemode)
            htmlpath = save_plotly_html(fig) if exporthtml else None
            return fig, htmlpath, f"Rendered Plotly map. HTML={bool(htmlpath)}"
        except Exception as e:
            return None, None, f"Plotly error: {e}"

    def explain_with_llm(self, question: str) -> str:
        if self.llm is None:
            return "LLM not configured. Set GOOGLE_API_KEY and install langchain-google-genai to enable explanations."
        desc = self.df_desc_json or ""
        schema = self.df_schema_json or ""
        prompt = (
            "You are an assistant explaining AIS preprocessing outputs. "
            "Use the dataset summary (pandas describe JSON) and a compact schema as context. "
            "Be concise, highlight anomalies, and suggest next steps.\n\n"
            f"DATA_SUMMARY_JSON:\n{desc}\n\n"
            f"DATA_SCHEMA_JSON:\n{schema}\n\n"
            f"USER_QUESTION:\n{question}\n\n"
            "Answer:"
        )
        try:
            resp = self.llm.invoke(prompt)
            return getattr(resp, "content", str(resp))
        except Exception as e:
            return f"LLM error: {e}"

    def send_plot_to_gemini(self, user_prompt: str, b64_png: Optional[str], model_name: str = "gemini-2.5-flash") -> str:
        """
        Sends the plot image (base64 PNG) plus text context to Gemini using google-generativeai SDK.
        If no image is present, sends text-only.
        """
        if not HAS_GOOGLE_SDK:
            return "google-generativeai SDK not installed. pip install google-generativeai"
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            return "GOOGLE_API_KEY not set."
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name)
            parts = []
            if b64_png:
                parts.append({
                    "inline_data": {
                        "mime_type": "image/png",
                        "data": b64_png,
                    }
                })
            ds = self.df_desc_json or ""
            sch = self.df_schema_json or ""
            text_context = (
                "Context: AIS data processing result. Use the image (if any) and the summary below.\n\n"
                f"DATA_SUMMARY_JSON:\n{ds}\n\nDATA_SCHEMA_JSON:\n{sch}\n\n"
                f"USER_PROMPT:\n{user_prompt}"
            )
            parts.append({"text": text_context})
            resp = model.generate_content(parts)
            return resp.text if hasattr(resp, "text") and resp.text else str(resp)
        except Exception as e:
            return f"Gemini error: {e}"


agent = AISAgent()

# ---------- Gradio UI ----------
with gr.Blocks(theme=gr.themes.Soft(primary_hue="blue", neutral_hue="slate")) as demo:
    gr.Markdown("# AIS Agent\nA smoother, chat-first UI with tool actions and live previews.")

    # App state
    state_df = gr.State(None)                # pandas DataFrame
    state_last_csv = gr.State(None)          # path to last processed CSV
    state_last_png = gr.State(None)          # path to last PNG
    state_last_pdf = gr.State(None)          # path to last PDF
    state_last_b64 = gr.State(None)          # last PNG as base64
    state_result_text = gr.State("")         # last result summary

    # Top bar: upload + quick actions
    with gr.Row():
        upload = gr.File(label="Upload AIS CSV (.csv)", file_types=[".csv"])
        upload_status = gr.Markdown("")

    # Left: chat; Right: tools
    with gr.Row(variant="panel"):
        with gr.Column(scale=2, min_width=460):
            chat = gr.Chatbot(label="Assistant", type="messages", height=440, avatar_images=(None, None))
            gr.Markdown("Ask anything or run actions via slash-commands, e.g. `/process`, `/plot`, `/plotly`, `/explain`, `/gemini`.")
            user_box = gr.Textbox(placeholder="Type a message or a slash-command...", show_label=False)
            send_btn = gr.Button("Send", variant="primary")

        with gr.Column(scale=1, min_width=380):
            with gr.Tab("Process"):
                gr.Markdown("Select steps and parameters, then click Process or type `/process` in chat.")
                steps = gr.CheckboxGroup(
                    label="Steps",
                    choices=["Split by time", "Encode track", "Discretize H3", "Detect stops", "Add bathymetry", "Add weather"],
                    value=["Split by time"]
                )
                with gr.Row():
                    gapminutes = gr.Number(value=4320, label="Gap minutes")
                    timesplitdays = gr.Number(value=15, label="Time split (days)")
                with gr.Row():
                    encodedistance = gr.Number(value=200000, label="Encode distance (m)")
                    encodespeed = gr.Number(value=50, label="Encode speed (knots)")
                with gr.Row():
                    h3res = gr.Number(value=6, label="H3 resolution")
                rasterpath = gr.Textbox(label="Bathymetry raster (GeoTIFF)", placeholder="path/to/bathy.tif")
                weathertext = gr.Textbox(
                    label="Weather shortnames CSV/JSON",
                    placeholder="Examples: '10u,10v,msl' OR one-column CSV OR JSON like {'shortnames':['10u','10v'],'start':'2024-01-01','end':'2024-01-31'}"
                )
                with gr.Row():
                    distancesplitm = gr.Number(value=30000, label="Distance split (m)")
                    speedsplitkn = gr.Number(value=30, label="Speed split (knots)")
                process_btn = gr.Button("Process", variant="primary")
                resulttxt = gr.Textbox(label="Result", lines=8)
                downloadcsv = gr.File(label="Download processed CSV")

            with gr.Tab("Static Plot"):
                enableplot = gr.Checkbox(label="Enable Matplotlib/Cartopy", value=True)
                with gr.Row():
                    usecartopy = gr.Checkbox(label="Use Cartopy (if installed)", value=True)
                    addcoastlines = gr.Checkbox(label="Add coastlines", value=True)
                with gr.Row():
                    exportpng = gr.Checkbox(label="Export PNG", value=True)
                    exportpdf = gr.Checkbox(label="Export PDF", value=True)
                plot_btn = gr.Button("Render Static Plot")
                plotimg = gr.Image(label="PNG preview", interactive=False)
                plotpdf = gr.File(label="Download PDF")
                plotstatus = gr.Textbox(label="Plot status", interactive=False)
                plot_b64_txt = gr.Textbox(label="Base64 PNG (for Gemini)", lines=4)

            with gr.Tab("Plotly OSM"):
                enableplotly = gr.Checkbox(label="Use Plotly OpenStreetMap", value=False)
                plotly_linemode = gr.Checkbox(label="Line mode (lines+markers)", value=True)
                exporthtml = gr.Checkbox(label="Export Plotly HTML", value=True)
                plotly_btn = gr.Button("Render Plotly OSM")
                plotlyfig = gr.Plot(label="Plotly OSM (interactive)")
                plotlyhtml = gr.File(label="Download Plotly HTML")
                plotlystatus = gr.Textbox(label="Plotly status", interactive=False)

            with gr.Tab("Explain"):
                explainin = gr.Textbox(label="Question about the data or results")
                explainbtn = gr.Button("Ask")
                explainout = gr.Textbox(label="Explanation", lines=12)

            with gr.Tab("Gemini"):
                gemini_prompt = gr.Textbox(label="Prompt", placeholder="Ask Gemini about the plot and data...")
                gemini_btn = gr.Button("Send to Gemini")
                gemini_out = gr.Textbox(label="Gemini Response", lines=12)

    # Helpers
    def parse_weather_cfg(wtext: str):
        wc = None
        shortnames_override = None
        try:
            shortnames_override = parse_shortnames_from_csvish(wtext) or None
            if shortnames_override is None and wtext and wtext.strip():
                wc = json.loads(wtext)
        except Exception:
            wc = None
        if shortnames_override:
            if wc is None:
                wc = {}
            wc["shortnames"] = shortnames_override
        return wc, shortnames_override

    # Upload handler
    def on_upload(fileobj, history):
        try:
            fp = getattr(fileobj, "name", None)
            if fp is None:
                tpath = tempfile.mktemp(suffix=".csv", dir=os.environ.get("GRADIO_TEMP_DIR", tempfile.gettempdir()))
                with open(tpath, "wb") as f:
                    f.write(fileobj.read())
                fp = tpath
            msg = agent.load_csv(fp)
            history = (history or []) + [{"role": "assistant", "content": msg}]
            return msg, agent.df, agent.last_output_csv, history
        except Exception as e:
            err = f"Upload error: {e}"
            history = (history or []) + [{"role": "assistant", "content": err}]
            return err, None, None, history

    upload.change(
        fn=on_upload,
        inputs=[upload, chat],
        outputs=[upload_status, state_df, state_last_csv, chat]
    )

    # Core actions
    def do_process(stepssel, gap, dist, spd, res, rpath, wtext, tsdays, dsm, sskn):
        wc, _ = parse_weather_cfg(wtext or "")
        msg = agent.process_steps(
            steps=list(stepssel or []),
            gapminutes=int(gap or 4320),
            encodedistancem=float(dist or 200000),
            encodespeedkn=float(spd or 50),
            h3res=int(res or 6),
            rasterpath=rpath or None,
            weathercfg=wc,
            timesplitdays=float(tsdays) if tsdays is not None else None,
            distancesplitm=float(dsm) if dsm is not None else None,
            speedsplitkn=float(sskn) if sskn is not None else None,
        )
        out_csv = agent.last_output_csv if agent.last_output_csv and os.path.exists(agent.last_output_csv) else None
        return msg, out_csv

    def do_plot(a_enableplot, a_usecartopy, a_addcoastlines, a_exportpng, a_exportpdf):
        png_path, pdf_path, plot_status, b64_png = agent.plot_tracks(
            enableplot=a_enableplot,
            usecartopy=a_usecartopy,
            addcoastlines=a_addcoastlines,
            exportpng=a_exportpng,
            exportpdf=a_exportpdf
        )
        return png_path, pdf_path, plot_status, b64_png

    def do_plotly(a_enable, a_linemode, a_exporthtml):
        fig, htmlpath, status = agent.plot_tracks_plotly(a_enable, a_linemode, a_exporthtml)
        return fig, htmlpath, status

    def do_explain(q):
        return agent.explain_with_llm(q)

    def do_gemini(prompt_text, b64_png):
        return agent.send_plot_to_gemini(prompt_text or "Describe this plot and dataset.", b64_png or agent.last_plot_b64)

    # Wire buttons
    def on_process_click(stepssel, gap, dist, spd, res, rpath, wtext, tsdays, dsm, sskn, history):
        try:
            msg, out_csv = do_process(stepssel, gap, dist, spd, res, rpath, wtext, tsdays, dsm, sskn)
            history = (history or []) + [{"role": "assistant", "content": msg}]
            return msg, out_csv, history
        except Exception as e:
            err = f"Error: {e}"
            history = (history or []) + [{"role": "assistant", "content": err}]
            return err, None, history

    process_btn.click(
        fn=on_process_click,
        inputs=[steps, gapminutes, encodedistance, encodespeed, h3res, rasterpath, weathertext,
                timesplitdays, distancesplitm, speedsplitkn, chat],
        outputs=[resulttxt, downloadcsv, chat]
    )

    def on_plot_click(a_enableplot, a_usecartopy, a_addcoastlines, a_exportpng, a_exportpdf, history):
        try:
            png_path, pdf_path, plot_status, b64_png = do_plot(a_enableplot, a_usecartopy, a_addcoastlines, a_exportpng, a_exportpdf)
            history = (history or []) + [{"role": "assistant", "content": plot_status}]
            return png_path, pdf_path, plot_status, b64_png, png_path, pdf_path, b64_png, history
        except Exception as e:
            err = f"Plot error: {e}"
            history = (history or []) + [{"role": "assistant", "content": err}]
            return None, None, err, None, None, None, None, history

    plot_btn.click(
        fn=on_plot_click,
        inputs=[enableplot, usecartopy, addcoastlines, exportpng, exportpdf, chat],
        outputs=[plotimg, plotpdf, plotstatus, plot_b64_txt, state_last_png, state_last_pdf, state_last_b64, chat]
    )

    plotly_btn.click(
        fn=do_plotly,
        inputs=[enableplotly, plotly_linemode, exporthtml],
        outputs=[plotlyfig, plotlyhtml, plotlystatus]
    )

    explainbtn.click(fn=do_explain, inputs=explainin, outputs=explainout)
    gemini_btn.click(fn=do_gemini, inputs=[gemini_prompt, plot_b64_txt], outputs=gemini_out)

    # Chat commands
    def handle_chat(message, history,
                    stepssel, gap, dist, spd, res, rpath, wtext, tsdays, dsm, sskn,
                    a_enableplot, a_usecartopy, a_addcoastlines, a_exportpng, a_exportpdf):
        history = history or []
        history = history + [{"role": "user", "content": message}]

        text = (message or "").strip()
        try:
            if text.startswith("/process"):
                msg, out_csv = do_process(stepssel, gap, dist, spd, res, rpath, wtext, tsdays, dsm, sskn)
                history = history + [{"role": "assistant", "content": msg}]
                return history, msg, out_csv, agent.df, agent.last_output_csv, agent.last_plot_b64

            if text.startswith("/plotly"):
                _, htmlpath, status = do_plotly(True, True, True)
                history = history + [{"role": "assistant", "content": status}]
                return history, gr.update(), gr.update(), agent.df, agent.last_output_csv, agent.last_plot_b64

            if text.startswith("/plot"):
                png_path, pdf_path, plot_status, b64_png = do_plot(a_enableplot, a_usecartopy, a_addcoastlines, a_exportpng, a_exportpdf)
                history = history + [{"role": "assistant", "content": plot_status}]
                # return result text, download, state_df, state_last_csv, state_last_b64
                return history, plot_status, agent.last_output_csv, agent.df, png_path or agent.last_output_csv, b64_png

            if text.startswith("/explain"):
                q = text.replace("/explain", "", 1).strip() or "Summarize the processed dataset."
                ans = do_explain(q)
                history = history + [{"role": "assistant", "content": ans}]
                return history, ans, agent.last_output_csv, agent.df, agent.last_output_csv, agent.last_plot_b64

            if text.startswith("/gemini"):
                q = text.replace("/gemini", "", 1).strip() or "Describe this plot and dataset."
                ans = do_gemini(q, agent.last_plot_b64)
                history = history + [{"role": "assistant", "content": ans}]
                return history, ans, agent.last_output_csv, agent.df, agent.last_output_csv, agent.last_plot_b64

            fallback = "Use the action tabs or slash-commands: /process, /plot, /plotly, /explain <q>, /gemini <q>."
            history = history + [{"role": "assistant", "content": fallback}]
            return history, fallback, agent.last_output_csv, agent.df, agent.last_output_csv, agent.last_plot_b64
        except Exception as e:
            err = f"Error: {e}"
            history = history + [{"role": "assistant", "content": err}]
            return history, err, agent.last_output_csv, agent.df, agent.last_output_csv, agent.last_plot_b64

    send_btn.click(
        fn=handle_chat,
        inputs=[user_box, chat,
                steps, gapminutes, encodedistance, encodespeed, h3res, rasterpath, weathertext,
                timesplitdays, distancesplitm, speedsplitkn,
                enableplot, usecartopy, addcoastlines, exportpng, exportpdf],
        outputs=[chat, resulttxt, downloadcsv, state_df, state_last_csv, state_last_b64],
    )
    user_box.submit(
        fn=handle_chat,
        inputs=[user_box, chat,
                steps, gapminutes, encodedistance, encodespeed, h3res, rasterpath, weathertext,
                timesplitdays, distancesplitm, speedsplitkn,
                enableplot, usecartopy, addcoastlines, exportpng, exportpdf],
        outputs=[chat, resulttxt, downloadcsv, state_df, state_last_csv, state_last_b64],
    )

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, allowed_paths=[tempfile.gettempdir()],share=False)
