---
description: >-
  In this page, we will see how we can use AISdb to discretize AIS tracks to
  hexagons.
icon: hexagon
---

# Hexagon Discretization

## Introduction

H3 is Uber's hierarchical hexagonal geospatial indexing system. It partitions the Earth into a multi-resolution hexagonal grid, and its key advantage over square grids is the "one-distance rule," where all neighbors of a hexagon lie at comparable step distances.

<figure><img src="../.gitbook/assets/hex.png" alt=""><figcaption></figcaption></figure>

As illustrated in the figure above, this uniformity removes the diagonal-versus-edge ambiguity present in square lattices. For maritime work, hexagons are great because they reduce directional bias and make neighborhood queries and aggregation intuitive.

> H3 indexes are 64-bit IDs typically shown as hex strings, such as `860e4d31fffffff`.

### Discretize AIS lat/lon points to hexagons using AISdb

{% hint style="warning" %}
The `aisdb.discretize.h3` module landed after the 1.8.0-alpha release, so it is not in that tag or in the PyPI package. To follow this tutorial, install AISdb from the development branch with `pip install git+https://github.com/MAPS-Lab/AISdb.git` (a Rust toolchain is required to build it).
{% endhint %}

AISdb's `aisdb.discretize.h3.Discretizer` class wraps the [h3-py](https://uber.github.io/h3-py/) bindings so you can go from a stream of AIS tracks straight to H3 cell IDs, without hand-rolling the lat/lon-to-cell conversion yourself. The code below connects to a PostgreSQL database, queries a bounding box and time window in the Gulf of St. Lawrence, and tags each point in the resulting tracks with its H3 index.

{% code title="discretize_tracks.py" lineNumbers="true" %}
```python
import aisdb
from aisdb import DBQuery
from aisdb.database.dbconn import PostgresDBConn
from datetime import datetime, timedelta
from aisdb.discretize.h3 import Discretizer

# PostgreSQL connection details (replace placeholders or use environment variables)
db_user = '<>'             # PostgreSQL username
db_dbname = '<>'           # PostgreSQL database/schema name
db_password = '<>'         # PostgreSQL password
db_hostaddr = '127.0.0.1'  # PostgreSQL host address (localhost shown)

dbconn = PostgresDBConn(
    port=5555,             # PostgreSQL port (5432 is the default; 5555 here is just an example)
    user=db_user,
    dbname=db_dbname,
    hostaddr=db_hostaddr,
    password=db_password,
)

# Spatial and temporal query window over the Gulf of St. Lawrence
xmin, ymin, xmax, ymax = -70, 45, -58, 53
start_time = datetime(2023, 8, 1)
end_time = datetime(2023, 8, 2)

# DBQuery takes the bounding box as four separate keyword arguments, not a
# single bbox list, and the callback picks the SQL "WHERE" clause it applies.
qry = DBQuery(
    dbconn=dbconn,
    start=start_time, end=end_time,
    xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax,
    callback=aisdb.database.sqlfcn_callbacks.in_time_bbox_validmmsi,
)
rowgen = qry.gen_qry()

# A resolution of 6 gives hexagons roughly the size of a small region; raise
# it for finer grids, lower it for coarser ones.
discretizer = Discretizer(resolution=6)

# TrackGen groups the raw rows into per-vessel tracks, and split_timedelta
# breaks long tracks into fixed-length segments so a single vessel's history
# doesn't blend into one enormous track.
tracks = aisdb.track_gen.TrackGen(rowgen, decimate=True)
tracks_segment = aisdb.track_gen.split_timedelta(tracks, timedelta(weeks=4))

# yield_tracks_discretized_by_indexes adds an 'h3_index' array to each track,
# aligned point-for-point with its 'lat' and 'lon' arrays.
tracks_with_indexes = discretizer.yield_tracks_discretized_by_indexes(tracks_segment)

for track in tracks_with_indexes:
    print(f"H3 index for lat {track['lat'][0]}, lon {track['lon'][0]}: {track['h3_index'][0]}")
    break

# Output: H3 index for lat 50.003334045410156, lon -66.76000213623047: 860e4d31fffffff
```
{% endcode %}

The `Discretizer` also exposes a couple of methods worth knowing about beyond the streaming path above. `get_h3_index(lat, lon)` converts a single coordinate pair to its H3 cell ID, useful when you already have a point and don't need the full track pipeline. `get_polygon_from_cells(cells, tight=True)` takes a list of H3 cell IDs and returns their combined boundary as a Shapely geometry, handy for drawing the hexagon footprint of a set of cells on a map. And `describe()` prints and plots how hexagon area changes with latitude at the chosen resolution, plus a table of edge lengths across all 16 H3 resolutions, which is a quick way to sanity-check that the resolution you picked matches the scale of the analysis.

```python
# Inspect how resolution 6 hexagons scale with latitude and print edge lengths
discretizer.describe()
```

`describe()` relies on `matplotlib` and `geopandas`, both of which install automatically as core AISdb dependencies, so there's nothing extra to add.

Refer to the example notebook for the full walkthrough, including the `describe()` output. [https://github.com/MAPS-Lab/AISdb/blob/master/examples/discretize.ipynb](https://github.com/MAPS-Lab/AISdb/blob/master/examples/discretize.ipynb)

## References

1. [https://www.uber.com/en-CA/blog/h3/](https://www.uber.com/en-CA/blog/h3/)
