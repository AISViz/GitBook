---
icon: water
description: >-
  Extracting distance features from and to points-of-interest using raster
  files.
---

# 🏝️ Coast, shore, and ports

The distance of a vessel from the nearest shore, coast, and port is a useful feature for vessel behavior analysis, environmental monitoring, and maritime safety assessments. AISdb offers functions to acquire these distances for specific vessel positions using raster files sourced from NASA and Global Fishing Watch. In this tutorial, we calculate the distance in kilometers from shore, coast, and the nearest port for a sample track, then show how to fetch a list of real-world ports for a bounding box.

First, we create a sample track:

{% code lineNumbers="true" %}
```python
import numpy as np
import aisdb
from datetime import datetime
from aisdb.gis import dt_2_epoch

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

# creating a sample track
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
```
{% endcode %}

Here is what the sample track looks like:

<figure><img src="../.gitbook/assets/image (31).png" alt=""><figcaption><p>Sample track created for distance to shore and port calculation</p></figcaption></figure>

## Distance from shore, coast, and port

`ShoreDist`, `CoastDist`, and `PortDist` all follow the same pattern, downloading the relevant raster from the AISdb data release on GitHub, merging it against the provided track list, and storing the result under a new dynamic key.

{% tabs %}
{% tab title="ShoreDist" %}
The class [`aisdb.webdata.shore_dist.ShoreDist`](https://aisviz.cs.dal.ca/AISdb/api/aisdb.webdata.shore_dist.html#aisdb.webdata.shore_dist.ShoreDist) is used to calculate the nearest distance to shore, using a raster file containing shore distance data. Currently, calling the `get_distance` function in `ShoreDist` will automatically download the shore distance raster file from the AISdb data release on GitHub. The function then merges the tracks in the provided track list, creates a new key, "km\_from\_shore", and stores the shore distance as the value for this key.

{% code lineNumbers="true" %}
```python
from aisdb.webdata.shore_dist import ShoreDist

with ShoreDist(data_dir="./testdata/") as sdist:
        # Getting distance from shore for each point in the track
        for track in sdist.get_distance(tracks_short):
            assert 'km_from_shore' in track['dynamic']
            assert 'km_from_shore' in track.keys()
            print(track['km_from_shore'])
```
{% endcode %}

{% code lineNumbers="true" %}
```
[ 1  3  2  9 14]
```
{% endcode %}
{% endtab %}

{% tab title="CoastDist" %}
Similar to acquiring the distance from shore, `CoastDist` is implemented to obtain the distance between the given track positions and the coastline.

{% code lineNumbers="true" %}
```python
from aisdb.webdata.shore_dist import CoastDist

with CoastDist(data_dir="./testdata/") as cdist:
        # Getting distance from the coast for each point in the track
        for track in cdist.get_distance(tracks_short):
            assert 'km_from_coast' in track['dynamic']
            assert 'km_from_coast' in track.keys()
            print(track['km_from_coast'])
```
{% endcode %}

{% code lineNumbers="true" %}
```
[ 1  3  2  8 13]
```
{% endcode %}
{% endtab %}

{% tab title="PortDist" %}
Like the distances from the coast and shore, the [`aisdb.webdata.shore_dist.PortDist`](https://aisviz.cs.dal.ca/AISdb/api/aisdb.webdata.shore_dist.html#aisdb.webdata.shore_dist.PortDist) class determines the distance between the track positions and the nearest ports.

{% code lineNumbers="true" %}
```python
from aisdb.webdata.shore_dist import PortDist

with PortDist(data_dir="./testdata/") as pdist:
        # Getting distance from the port for each point in the track
        for track in pdist.get_distance(tracks_short):
            assert 'km_from_port' in track['dynamic']
            assert 'km_from_port' in track.keys()
            print(track['km_from_port'])
```
{% endcode %}

{% code lineNumbers="true" %}
```
[ 4.72144175  7.47747231  4.60478449 11.5642271  28.62511253]
```
{% endcode %}
{% endtab %}
{% endtabs %}

## Fetching a list of ports

{% hint style="warning" %}
The `aisdb.ports` module landed after the 1.8.0-alpha release, so it is not in that tag or in the PyPI package. To use `WorldPortIndexClient`, install AISdb from the development branch with `pip install git+https://github.com/MAPS-Lab/AISdb.git`. The raster distance classes above work on 1.8.0-alpha as-is.
{% endhint %}

`ShoreDist`, `CoastDist`, and `PortDist` all answer the same question from the vessel's side, how far is this point from a raster surface. Sometimes you need the opposite view, a list of the actual ports inside a region so you can label tracks, filter for cargo-capable harbors, or join port metadata onto your AIS data. AISdb exposes this through `aisdb.ports.api.WorldPortIndexClient`, which queries the World Port Index feature service maintained by the National Geospatial-Intelligence Agency and returns the result as a pandas DataFrame.

`fetch_ports` takes a bounding box as `lat_min`, `lat_max`, `lon_min`, `lon_max`, and returns every port whose coordinates fall inside it. Passing `save=True` along with `out_path` writes the result to a CSV file as well. The example below queries the Gulf of St. Lawrence, then narrows the result to ports with a usable cargo depth using `filter_by_cargo_depth`.

{% code lineNumbers="true" %}
```python
from aisdb.ports.api import WorldPortIndexClient

client = WorldPortIndexClient()

# Query the Gulf of St. Lawrence region
df_ports = client.fetch_ports(
    lat_min=45.0,
    lat_max=51.5,
    lon_min=-71.5,
    lon_max=-55.0
)

# Filter for cargo-capable ports
df_cargo = client.filter_by_cargo_depth(df_ports)
```
{% endcode %}

Each row in `df_ports` carries the port's `LAT` and `LON` columns along with the full set of World Port Index fields, such as `PORT_NAME` and `HARBORSIZE`. From here it is straightforward to combine the port list with the [hexagon discretization](hexagon-discretization.md) tutorial, indexing each port with `aisdb.discretize.h3.Discretizer` so it shares the same spatial grid as your decoded AIS tracks, or joining `km_from_port` values back to the nearest named port for reporting.
