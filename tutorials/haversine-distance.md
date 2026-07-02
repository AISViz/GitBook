---
icon: globe
description: >-
  Compute great-circle distance between AIS positions with the haversine
  formula, including 3D distance to a submerged reference point.
---

# 🌎 Haversine Distance

Two AIS positions are almost never on a flat plane. A vessel moving between consecutive reports is tracing an arc across a curved Earth, and treating that arc as a straight line introduces error that grows with distance. **AISdb** solves this with the haversine formula, which computes great-circle distance directly from pairs of latitude/longitude coordinates. The formula itself is implemented in Rust for speed and exposed to Python as `aisdb.gis.delta_meters`, which <mark style="background-color:yellow;">calculates the haversine distance in meters between consecutive positions within a vessel track.</mark> This is the building block behind several other AISdb calculations, including [vessel speed](vessel-speed.md) and the [denoising encoder](https://aisviz.cs.dal.ca/AISdb/api/aisdb.denoising_encoder.html#aisdb.denoising_encoder.encode_greatcircledistance), which compares consecutive-position distances against a threshold to help flag noisy AIS pings.

Here is an example of calculating the haversine distance between each pair of consecutive points on a track:

{% code lineNumbers="true" %}
```python
import aisdb
import numpy as np
from aisdb.gis import dt_2_epoch
from datetime import datetime

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
        lon=np.array([x1, x2, x3, x4, x5]),
        lat=np.array([y1, y2, y3, y4, y5]),
        time=np.array([t1, t2, t3, t4, t5]),
        mmsi=123456789,
        dynamic=set(['lon', 'lat', 'time']),
        static=set(['mmsi'])
    )
]

# Calculate the Haversine distance
for track in tracks_short:
    print(aisdb.gis.delta_meters(track))
```
{% endcode %}

{% code lineNumbers="true" %}
```
[ 6961.401286 6948.59446128 7130.40147082 57279.94580704]
```
{% endcode %}

`delta_meters` returns one value fewer than the number of positions in the track, because each output is the distance between a position and the one that follows it. The last leg (57,279 meters) is noticeably longer than the first three, which makes sense given the three-hour gap between `t4` and `t5` in the timestamps above, plenty of time for a vessel to cover more ground.

If we visualize this track on the map, we can observe:

<figure><img src="../.gitbook/assets/image (7).png" alt=""><figcaption></figcaption></figure>

## Distance to a submerged point

The haversine formula only accounts for horizontal distance across the Earth's surface. When the reference point isn't at sea level, such as a hydrophone, a pipeline, or any other piece of subsea infrastructure, AISdb adds a vertical (depth) component using `aisdb.gis.distance3D`. It combines the haversine distance with the depth via the Pythagorean theorem, treating the depth as the third leg of a right triangle:

$$
Distance_{3D} = \sqrt{Haversine\ Distance^2 + Depth^2}
$$

`aisdb.gis.vesseltrack_3D_dist` applies this calculation across an entire track, appending the result to each position under a new dynamic key (`distance_metres` by default). Reusing the track from above, here is the distance from each position to a fixed subsea point 150 meters below the surface, near the entrance to Halifax Harbour:

{% code lineNumbers="true" %}
```python
# Subsea reference point (longitude, latitude, depth in meters)
x1, y1, z1 = -63.55, 44.6, 150

tracks_3d = aisdb.gis.vesseltrack_3D_dist(tracks_short, x1=x1, y1=y1, z1=z1)

for track in tracks_3d:
    print(track['distance_metres'])
```
{% endcode %}

{% code lineNumbers="true" %}
```
[3680.166945539894 10636.724472053462 15827.101419957418 22932.09964031206
 70614.73404949748]
```
{% endcode %}

Unlike `delta_meters`, this returns one value per position rather than one per leg, since each distance is measured from the fixed subsea point rather than between consecutive track positions.
