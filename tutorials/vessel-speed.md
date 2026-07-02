---
icon: gauge-high
description: >-
  Calculate vessel speed over ground in knots between consecutive AIS
  positions, and use it to flag implausible track jumps.
---

# 🚤 Vessel Speed

In **AISdb**, the speed of a vessel is calculated using the `aisdb.gis.delta_knots` function, which <mark style="background-color:yellow;">computes the speed over ground (SOG) in knots</mark> between consecutive positions within a given track. This calculation matters for the [denoising encoder](https://aisviz.cs.dal.ca/AISdb/api/aisdb.denoising_encoder.html#aisdb.denoising_encoder.encode_greatcircledistance), which compares a vessel's speed against a set threshold to flag implausible jumps in the data.

Vessel speed calculation requires the **distance** the vessel has traveled between two consecutive positions and the **time interval** between them. The distance is computed using the [haversine distance](https://aisviz.cs.dal.ca/AISdb/api/aisdb.gis.html#aisdb.gis.delta_meters) function (`aisdb.gis.delta_meters`), and the time interval comes from [`aisdb.gis.delta_seconds`](https://aisviz.cs.dal.ca/AISdb/api/aisdb.gis.html#aisdb.gis.delta_seconds), which takes the difference between consecutive timestamps in a track's `time` array. The speed is then computed using the formula:

$$
Speed(knot) = \frac{Haversine Distance}{Time} \times 1.9438445
$$

The factor `1.9438445` converts speed from meters per second to knots, the standard speed unit used in maritime contexts. Internally, `delta_knots` clamps each elapsed-time value to a minimum of one second before dividing, so a duplicate or near-duplicate timestamp in a track can't produce a division by zero or an unrealistically inflated speed.

With the example track we created in [_Haversine Distance_](haversine-distance.md), we can calculate the vessel speed between each pair of consecutive positions:

{% code lineNumbers="true" %}
```python
import aisdb
import numpy as np
from datetime import datetime
from aisdb.gis import dt_2_epoch

# Generate example track
y1, x1 = 44.57039426840729, -63.52931373766157
y2, x2 = 44.51304767533133, -63.494075674952555
y3, x3 = 44.458038982492134, -63.535634138077945
y4, x4 = 44.393941339104074, -63.53826396955358
y5, x5 = 44.14245580737021, -64.16608964280064

t1 = dt_2_epoch( datetime(2021, 1, 1, 1) )
t2 = dt_2_epoch( datetime(2021, 1, 1, 2) )
t3 = dt_2_epoch( datetime(2021, 1, 1, 3) )
t4 = dt_2_epoch( datetime(2021, 1, 1, 4) )
t5 = dt_2_epoch( datetime(2021, 1, 1, 7) )

# Create a sample track
tracks_short = [
    dict(
        mmsi=123456789,
        lon=np.array([x1, x2, x3, x4, x5]),
        lat=np.array([y1, y2, y3, y4, y5]),
        time=np.array([t1, t2, t3, t4, t5]),
        dynamic=set(['lon', 'lat', 'time']),
        static=set(['mmsi'])
    )
]

# Calculate the vessel speed in knots
for track in tracks_short:
    print(aisdb.gis.delta_knots(track))
```
{% endcode %}

{% code lineNumbers="true" %}
```
[3.7588560005768947 3.7519408684140214 3.8501088005116215 10.309565520121597]
```
{% endcode %}

The four values correspond to the four gaps between the five positions in the track. The first three positions are an hour apart and produce speeds around 3.8 knots, consistent with a vessel moving at a leisurely pace. The gap between the fourth and fifth positions spans three hours and covers a much greater distance, which is why the last value jumps to roughly 10.3 knots. This is exactly the kind of signal `aisdb.denoising_encoder.remove_pings_wrt_speed` relies on when filtering a track. A speed that spikes far above what a vessel of that type could plausibly sustain usually points to a corrupted or duplicated AIS position report rather than real movement.
