---
description: >-
  Denoise AIS tracks with AISdb, removing duplicate-identifier jumps,
  anchored vessels, and land-locked positions before analysis.
icon: broom
---

# 🚿 Data Cleaning

A common issue with AIS data is noise, where multiple vessels transmit under the same identifier, receivers pick up corrupted or drifting positions, or a single vessel's track jumps in ways no real ship could follow. AISdb ships a dedicated denoising module, [`aisdb.denoising_encoder`](https://aisviz.cs.dal.ca/AISdb/api/aisdb.denoising_encoder.html), to detect and correct these problems before a track is analyzed or visualized.

The module exposes three functions and one class, each targeting a different kind of noise.

* `encode_greatcircledistance()` splits a track wherever consecutive pings imply an impossible speed or distance, then reassembles the pieces that most plausibly belong together.
* `encode_score()` is the scoring function that `encode_greatcircledistance()` uses internally to decide which segments belong to the same voyage. It is also available on its own for custom pipelines.
* `remove_pings_wrt_speed()` drops pings recorded while a vessel was moving at or below a speed threshold, which is the fast way to strip out anchored or moored vessels.
* `InlandDenoising` removes points that fall on land, using cached land and water geometries for North America.

## Segmenting and re-linking tracks with `encode_greatcircledistance()`

The core idea behind `encode_greatcircledistance()` is that a real vessel's positions form a continuous, physically plausible path. When two consecutive pings imply a speed or distance that no vessel could achieve, that is a strong signal of noise, whether from a duplicate MMSI, a receiver glitch, or a spoofed identifier. The function walks each track and cuts it into segments wherever this happens.

### How segmentation and re-linking work

`encode_greatcircledistance()` takes two thresholds to decide where to cut a track.

* `distance_threshold` is the maximum distance, in meters, allowed between consecutive pings for them to be treated as part of the same segment.
* `speed_threshold` is the maximum speed, in knots, a vessel can plausibly travel between consecutive pings.

Once a track is cut into candidate segments, the function does not just discard the fragments. It calls `encode_score()` to compute a score for every pair of segments, the score being the Haversine distance between the end of one segment and the start of the next, divided by the elapsed time between them. Segments with a short gap in both time and space score higher, meaning they are more likely to belong to the same voyage. A segment is joined to the highest-scoring candidate segment for the same MMSI, provided the score meets `minscore`. If no candidate segment clears that bar, the segment starts a new, independent track.

This is why `encode_greatcircledistance()` works well against duplicate-identifier noise. Two different vessels broadcasting the same MMSI produce position jumps that fail the distance and speed thresholds, so the encoder splits them apart. Each resulting segment is then re-linked only to segments that are geographically and temporally consistent with it, effectively separating the interleaved tracks of the two vessels back into two coherent trajectories.

### Example

The following example queries a day of traffic around Halifax harbour, splits the resulting tracks on long time gaps, then runs the great-circle-distance encoder before visualizing the result.

{% code title="clean_tracks.py" lineNumbers="true" %}
```python
import aisdb
from datetime import datetime, timedelta
from aisdb import DBQuery, DomainFromPoints, SQLiteDBConn

dbpath = 'YOUR_DATABASE.db'  # path to your AISdb database

# Query window
start_time = datetime.strptime('2018-01-01 00:00:00', '%Y-%m-%d %H:%M:%S')
end_time = datetime.strptime('2018-01-02 00:00:00', '%Y-%m-%d %H:%M:%S')

# A bounding box with at least a 50km radius around the given point
domain = DomainFromPoints(points=[(-63.6, 44.6)], radial_distances=[50000])

maxdelta = timedelta(hours=24)   # split a track wherever the time gap exceeds this
distance_threshold = 20000       # max allowed distance (meters) between consecutive pings
speed_threshold = 50             # max plausible vessel speed (knots) between consecutive pings
minscore = 1e-6                  # minimum score required to re-link two segments

with SQLiteDBConn(dbpath=dbpath) as dbconn:
    qry = DBQuery(
        dbconn=dbconn,
        start=start_time,
        end=end_time,
        callback=aisdb.database.sqlfcn_callbacks.in_timerange_validmmsi,
        **domain.boundary,
    )
    rowgen = qry.gen_qry()
    tracks = aisdb.TrackGen(rowgen, decimate=False)

    # Split tracks wherever the gap between pings exceeds maxdelta
    track_segments = aisdb.split_timedelta(tracks, maxdelta)

    # Re-link the segments using distance, speed, and score thresholds
    tracks_encoded = aisdb.encode_greatcircledistance(
        track_segments,
        distance_threshold=distance_threshold,
        speed_threshold=speed_threshold,
        minscore=minscore,
    )

    aisdb.web_interface.visualize(
        tracks_encoded,
        domain=domain,
        visualearth=True,
        open_browser=True,
    )
```
{% endcode %}

Processing functions like `split_timedelta()` and `encode_greatcircledistance()` can be chained this way because each one accepts a track generator and returns a track generator. Segmenting on time gaps first, then encoding, keeps the encoder from wasting effort trying to re-link pings that are already known to belong to separate voyages.

After segmentation and encoding, the tracks look like this.

<figure><img src="../.gitbook/assets/Screenshot from 2024-08-07 16-37-54.png" alt=""><figcaption><p>Queried vessel tracks after applying track segmentation and encoder (distance threshold=20km, speed threshold=50knots)</p></figcaption></figure>

For comparison, here is the same area before cleaning.

<figure><img src="../.gitbook/assets/image (28).png" alt=""><figcaption><p>Queried vessel tracks before cleaning</p></figcaption></figure>

{% hint style="info" %}
To color-code the resulting tracks before visualizing, write a small generator that sets a `color` key on each track dict, for example `track['color'] = 'red'` or an RGB string such as `'rgb(255,0,0)'`, and pass the output through it before calling `aisdb.web_interface.visualize()`.
{% endhint %}

## Removing anchored vessels with `remove_pings_wrt_speed()`

Not all noise comes from broken identifiers. Vessels sitting at anchor or moored at a berth broadcast steadily over long periods, and their pings can dominate a query or clutter a map without adding any useful trajectory information. `remove_pings_wrt_speed()` filters these out directly by removing any ping where the reported speed over ground (`sog`) is less than or equal to a given `speed_threshold`, expressed in knots.

```python
import aisdb

with aisdb.SQLiteDBConn(dbpath=dbpath) as dbconn:
    qry = aisdb.DBQuery(
        dbconn=dbconn,
        start=start_time,
        end=end_time,
        callback=aisdb.database.sqlfcn_callbacks.in_timerange_validmmsi,
    )
    tracks = aisdb.TrackGen(qry.gen_qry(), decimate=False)

    # Drop pings recorded at 0.5 knots or slower, i.e. vessels not really moving
    moving_tracks = aisdb.remove_pings_wrt_speed(tracks, speed_threshold=0.5)
```

Because this function only looks at reported speed, it is cheap to run early in a pipeline, before the more expensive distance and score computations in `encode_greatcircledistance()`.

## Filtering points on land with `InlandDenoising`

GPS drift and receiver noise occasionally place a vessel's reported position on land, which is physically impossible for anything but the smallest amphibious craft. `InlandDenoising`, from `aisdb.denoising_encoder`, checks each point in a track against cached land and water geometries and drops the ones that fall on land but not in water.

The class downloads a bundle of North American land and water geometries on first use and caches it locally, so construction takes a data directory and, optionally, the cache filenames to use.

```python
from aisdb.denoising_encoder import InlandDenoising

with InlandDenoising(data_dir='./inland_cache') as denoiser:
    clean_tracks = denoiser.filter_noisy_points(tracks)

    for track in clean_tracks:
        print(track['mmsi'], track['lon'].size)
```

```
316001234 187
```

The number after the MMSI is how many points survived the land check for that track, so a smaller count than the raw input means the denoiser found and dropped land-locked positions. The MMSIs and counts you get depend on the query window and coastline covered by your own data.

`filter_noisy_points()` accepts a track generator and yields cleaned tracks with the land-locked points removed, so it slots into the same pipeline pattern as the other denoising functions. Because the geometry bundle currently covers North America, this technique is most useful for AIS data collected along the Canadian and US coasts.

## Putting it together

None of these functions require the others, so pick whichever combination matches the noise in your data. A typical pipeline for coastal AIS data looks like this.

1. Query and generate tracks with `DBQuery` and `aisdb.TrackGen`.
2. Split tracks on large time gaps with `aisdb.split_timedelta()`.
3. Drop anchored vessels with `aisdb.remove_pings_wrt_speed()`, if stationary traffic is not of interest.
4. Re-link segments and separate duplicate-identifier tracks with `aisdb.encode_greatcircledistance()`.
5. Optionally, remove land-locked points with `InlandDenoising` if the query area includes a coastline.
6. Visualize or export the cleaned tracks.

Each step operates on generators, so the whole pipeline stays memory-efficient even over large queries, and you can drop or reorder steps depending on what kind of noise your dataset actually has.
