---
description: >-
  Query AIS data loaded with AISdb using DBQuery and TrackGen, with practical
  examples for time range, bounding box, and MMSI filters.
icon: magnifying-glass
---

# 🔎 Data Querying

Data querying with **AISdb** involves setting up a connection to the database, defining query parameters, creating and executing the query, and processing the results. Following the previous tutorial, [_Database Loading_](database-loading.md), we set up a database connection and made simple queries and visualizations. This tutorial will dig into data query functions and parameters and show you the queries you can make with AISdb.

## Query functions

Data querying with AISdb involves two components, `DBQuery` and `TrackGen`. In this section, we will introduce each component with examples. Before starting data querying, please ensure you have connected to the database. If you have not done so, please follow the instructions and examples in [_Database Loading_](database-loading.md#id-2.-load-ais-data-into-a-database) or [_Quick Start_](../default-start/quick-start.md#database-handling).&#x20;

### Query database

The [`DBQuery`](https://aisviz.cs.dal.ca/AISdb/api/aisdb.database.dbqry.html) class is used to <mark style="background-color:yellow;">**create a query object**</mark> that specifies the parameters for data retrieval, including the time range, spatial domain, and any filtering callbacks. Here is an example of creating a DBQuery object and using parameters to specify the time range and geographical locations:

{% code lineNumbers="true" %}
```python
import aisdb

# Specify database path
dbpath = 'YOUR_DATABASE.db'

# Specify constraints (optional)
start_time = ...
end_time = ...
domain = ...

with aisdb.SQLiteDBConn(dbpath=dbpath) as dbconn:
    # Create a query object to fetch data within time and geographical range
    qry = aisdb.DBQuery(
        dbconn=dbconn,                   # Database connection object
        start=start_time,                # Start time for the query
        end=end_time,                    # End time for the query
        xmin=domain.boundary['xmin'],    # Minimum longitude of the domain
        xmax=domain.boundary['xmax'],    # Maximum longitude of the domain
        ymin=domain.boundary['ymin'],    # Minimum latitude of the domain
        ymax=domain.boundary['ymax'],    # Maximum latitude of the domain
        callback=aisdb.database.sqlfcn_callbacks.in_time_bbox_validmmsi,  # Callback function to filter data
    )
```
{% endcode %}

#### Callback functions

Callback functions are used in the [`DBQuery`](https://aisviz.cs.dal.ca/AISdb/api/aisdb.database.dbqry.html) class to filter data based on specific criteria. Some common callbacks include `in_validmmsi_bbox`, `in_time_bbox`, `valid_mmsi`, and `in_time_bbox_validmmsi`. These callbacks ensure that the data retrieved matches the specific criteria defined in the query. Please find examples of using different callbacks with other parameters in [_Query types with practical examples_](data-querying.md#query-types-with-practical-examples).

For more callback functions, refer to the API documentation here: [API-Doc](https://aisviz.cs.dal.ca/AISdb/api/aisdb.database.sqlfcn_callbacks.html)

#### Method `gen_qry`

The method [`gen_qry`](https://aisviz.cs.dal.ca/AISdb/api/aisdb.database.dbqry.html#aisdb.database.dbqry.DBQuery.gen_qry) of the [`DBQuery`](https://aisviz.cs.dal.ca/AISdb/api/aisdb.database.dbqry.html) class runs the query and streams back the matching data. It does not yield one AIS record at a time. Instead, it is a generator that yields a batch of rows for each unique MMSI, sorted by MMSI first and then by time within each batch, fetching results in chunks under the hood so large queries stay memory-efficient. That grouping is exactly what `TrackGen` expects downstream, since a "track" is just a time-ordered run of positions for one vessel.

The SQL-generating function used internally is controlled by the `fcn` argument. AISdb ships two of them in `aisdb.database.sqlfcn`.

* `crawl_dynamic` iterates only over the position reports table. This is the default.
* `crawl_dynamic_static` iterates over both the position reports and static message tables, so each row also carries fields such as vessel name and ship type.

After creating the `DBQuery` object, generate the grouped rows with `gen_qry`.

{% code lineNumbers="true" %}
```python
from aisdb.database import sqlfcn

# Generate rows from the query, grouped by MMSI
rowgen = qry.gen_qry(fcn=sqlfcn.crawl_dynamic_static)  # fcn is optional, defaults to crawl_dynamic

# Each item is the list of rows belonging to a single vessel
for mmsi_rows in rowgen:
    print(f"{len(mmsi_rows)} rows for MMSI {mmsi_rows[0]['mmsi']}")
```
{% endcode %}

Each element of `mmsi_rows` is a `sqlite3.Row` (or a dict-like row when querying PostgreSQL) representing one position report. In practice you will rarely iterate `gen_qry` directly. Pass it straight to `TrackGen`, which does this grouping work for you and returns ready-to-use track dictionaries.

### Generate trajectories

The [`TrackGen`](https://aisviz.cs.dal.ca/AISdb/api/aisdb.track_gen.html#aisdb.track_gen.TrackGen) class <mark style="background-color:yellow;">**converts the generated rows**</mark> <mark style="background-color:yellow;"></mark><mark style="background-color:yellow;">from</mark> <mark style="background-color:yellow;"></mark><mark style="background-color:yellow;">`gen_qry`</mark> <mark style="background-color:yellow;">**into tracks (trajectories)**</mark>. It takes the row generator and, optionally, a `decimate` parameter to control point reduction. This conversion is essential for analyzing vessel movements, identifying patterns, and visualizing trajectories in later steps.

Following the generated rows above, here is how to use the `TrackGen` class:

{% code lineNumbers="true" %}
```python
from aisdb.track_gen import TrackGen

# Convert the generated rows into tracks
tracks = TrackGen(rowgen, decimate=False)
```
{% endcode %}

The `TrackGen` class returns a generator object that yields "tracks." While iterating over the tracks, each item is a dictionary representing the track of a specific vessel:

{% code lineNumbers="true" %}
```python
for track in tracks:
    mmsi = track['mmsi']
    lons = track['lon']
    lats = track['lat']
    speeds = track['sog']
    
    print(f"Track for vessel MMSI {mmsi}:")
    for lon, lat, speed in zip(lons[:3], lats[:3], speeds[:3]):
        print(f" - Lon: {lon}, Lat: {lat}, Speed: {speed}")
    break  # Exit after the first track
```
{% endcode %}

This is the output with our sample data:

{% code lineNumbers="true" %}
```
Track for vessel MMSI 316004240:
 - Lon: -63.54868698120117, Lat: 44.61691665649414, Speed: 7.199999809265137
 - Lon: -63.54880905151367, Lat: 44.61708450317383, Speed: 7.099999904632568
 - Lon: -63.55659866333008, Lat: 44.626953125, Speed: 1.5
```
{% endcode %}

## Query types with practical examples

In this section, we will provide practical examples of the most common query types you can make using the `DBQuery` class, including querying within a time range, querying within a geographical area, and tracking vessels by MMSI. Different queries can be achieved by changing the [`callbacks`](https://aisviz.cs.dal.ca/AISdb/api/aisdb.database.sqlfcn_callbacks.html#module-aisdb.database.sqlfcn_callbacks) parameter and other parameters defined in the `DBQuery` class. Then, we will use `TrackGen` to convert these query results into structured tracks for further analysis and visualization.

First, we need to import the necessary packages and prepare data:

{% code lineNumbers="true" %}
```python
import aisdb
from datetime import datetime
from aisdb import DomainFromPoints

dbpath = 'YOUR_DATABASE.db'  # Define the path to your database
```
{% endcode %}

### Within time range

Querying data within a specified time range can be done by using the [`in_timerange_validmmsi`](https://aisviz.cs.dal.ca/AISdb/api/aisdb.database.sqlfcn_callbacks.html#aisdb.database.sqlfcn_callbacks.in_timerange_validmmsi) callback in the `DBQuery` class:

{% code lineNumbers="true" %}
```python
start_time = datetime.strptime("2018-01-01 00:00:00", '%Y-%m-%d %H:%M:%S')
end_time = datetime.strptime("2018-01-02 00:00:00", '%Y-%m-%d %H:%M:%S')

with aisdb.SQLiteDBConn(dbpath=dbpath) as dbconn:
    qry = aisdb.DBQuery(
        dbconn=dbconn, start=start_time, end=end_time,
        callback=aisdb.database.sqlfcn_callbacks.in_timerange_validmmsi,
    )
    rowgen = qry.gen_qry()
    
    # Convert queried rows to vessel trajectories
    tracks = aisdb.track_gen.TrackGen(rowgen, decimate=False)
    
    # Visualization
    aisdb.web_interface.visualize(
        tracks,
        visualearth=True,
        open_browser=True,
    )
```
{% endcode %}

This will display the queried vessel tracks (within a time range, with a valid MMSI) on the map:

<figure><img src="../.gitbook/assets/Screenshot from 2024-08-07 14-12-48.png" alt=""><figcaption><p>Queried vessel tracks in specified time range</p></figcaption></figure>

You may find noise in some of the track data. In [_Data Cleaning_](data-cleaning.md), we introduced the de-noising methods in AISdb that can effectively remove unreasonable or erroneous data points, ensuring more accurate and reliable vessel trajectories.

### Within bounding box

In practical scenarios, people may have specific points/areas of interest. `DBQuery` includes parameters to define a bounding box and has relevant callbacks. Let's look at an example:

{% code lineNumbers="true" %}
```python
domain = DomainFromPoints(points=[(-63.6, 44.6)], radial_distances=[50000])  # a bounding box extending at least 50km from the point

with aisdb.SQLiteDBConn(dbpath=dbpath) as dbconn:
    qry = aisdb.DBQuery(
        dbconn=dbconn, start=start_time, end=end_time,
        xmin=domain.boundary['xmin'], xmax=domain.boundary['xmax'],
        ymin=domain.boundary['ymin'], ymax=domain.boundary['ymax'],
        callback=aisdb.database.sqlfcn_callbacks.in_validmmsi_bbox,
    )
    rowgen = qry.gen_qry()
    tracks = aisdb.track_gen.TrackGen(rowgen, decimate=False)
    
    aisdb.web_interface.visualize(
        tracks,
        domain=domain,
        visualearth=True,
        open_browser=True,
    )
```
{% endcode %}

This will show all the vessel tracks with valid MMSI in the defined bounding box:

<figure><img src="../.gitbook/assets/Screenshot from 2024-08-07 14-43-34.png" alt=""><figcaption><p>Queried vessel tracks within a defined bounding box</p></figcaption></figure>

### Combination of multiple conditions

In the above examples, we queried data in a time range and a geographical area. If you want to combine multiple query criteria, please check out available [types of callbacks](https://aisviz.cs.dal.ca/AISdb/api/aisdb.database.sqlfcn_callbacks.html#module-aisdb.database.sqlfcn_callbacks) in the API Docs. In the last example above, we can simply modify the callback type to obtain vessel tracks within both the time range and geographical area:

{% code lineNumbers="true" %}
```python
callback=aisdb.database.sqlfcn_callbacks.in_time_bbox_validmmsi
```
{% endcode %}

The displayed vessel tracks:

<figure><img src="../.gitbook/assets/Screenshot from 2024-08-07 14-58-47.png" alt=""><figcaption><p>Queried vessel tracks within a defined bounding box and time range</p></figcaption></figure>

### Filtering MMSI

In addition to time and location range, you can track one or more vessels of interest by specifying their MMSIs in the query. Here is an example of tracking several vessels within a time range:

{% code lineNumbers="true" %}
```python
import random

def assign_colors(mmsi_list):
    colors = {}
    for mmsi in mmsi_list:
        colors[mmsi] = "#{:06x}".format(random.randint(0, 0xFFFFFF))  # Random color in hex
    return colors

# Create a function to color tracks
def color_tracks(tracks, colors):
    colored_tracks = []
    for track in tracks:
        mmsi = track['mmsi']
        color = colors.get(mmsi, "#000000")  # Default to black if no color assigned
        track['color'] = color
        colored_tracks.append(track)
    return colored_tracks

# Set the start and end times for the query
start_time = datetime.strptime("2018-01-01 00:00:00", '%Y-%m-%d %H:%M:%S')
end_time = datetime.strptime("2018-12-31 00:00:00", '%Y-%m-%d %H:%M:%S')

# Create a list of vessel MMSIs you want to track 
MMSI = [636017611,636018124,636018253]

# Assign colors to each MMSI
colors = assign_colors(MMSI)

with aisdb.SQLiteDBConn(dbpath=dbpath) as dbconn:
    qry = aisdb.DBQuery(
        dbconn=dbconn, start=start_time, end=end_time, mmsis=MMSI,
        callback=aisdb.database.sqlfcn_callbacks.in_timerange_inmmsi,
    )
    rowgen = qry.gen_qry()
    
    tracks = aisdb.track_gen.TrackGen(rowgen, decimate=False)
    colored_tracks = color_tracks(tracks, colors)

    # Visualizing the tracks
    aisdb.web_interface.visualize(
        colored_tracks,
        visualearth=True,
        open_browser=True,
    )
```
{% endcode %}

<figure><img src="../.gitbook/assets/Screenshot from 2024-08-07 15-43-47.png" alt=""><figcaption><p>Queried tracks of vessels of interest within a specified time range</p></figcaption></figure>

## Where to go next

The tracks pulled here still carry the noise inherent to raw AIS, duplicate points, GPS jumps, and implausible speeds among them. See [data-cleaning.md](data-cleaning.md) for denoising them before further analysis. Once a track is clean, [data-visualization.md](data-visualization.md) covers plotting it on a map alongside other vessels and points of interest.
