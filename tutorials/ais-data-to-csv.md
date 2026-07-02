---
description: >-
  Export decoded AIS tracks from a SQLite or PostgreSQL AISdb database to
  CSV, using the built-in write_csv() writer or a custom column selection.
icon: file-csv
---

# 📒 AIS Data to CSV

Building on the [Database Loading](database-loading.md) tutorial, where we used AIS data to create AISdb databases, you can export that data back out to CSV for use in spreadsheets, R, pandas, or any tool that doesn't speak SQLite or PostgreSQL directly. AISdb ships a built-in writer for this, <mark style="background-color:yellow;">`aisdb.write_csv()`</mark>, which takes a track generator and handles column ordering, static-versus-dynamic fields, and value sanitization for you. This section covers that built-in path first, then shows how to write a custom CSV yourself when you only want a handful of columns.

## Exporting to CSV

Connect to the database, run a query, and hand the resulting tracks to `aisdb.write_csv()`. The whole flow, query and write, needs to happen inside the same `with` block, because `TrackGen` and `DBQuery.gen_qry()` are lazy generators that read from the database connection as they're consumed. Once the `with` block exits and the connection closes, iterating over `tracks` later will fail. The pattern is identical for SQLite and PostgreSQL, only the connection object changes; `PostgresDBConn` accepts the same keyword arguments as `psycopg`, including `host`, `port`, `user`, `dbname`, and `password`, or a single `libpq_connstring`.

{% tabs %}
{% tab title="SQLite" %}
{% code title="export_sqlite.py" lineNumbers="true" %}
```python
import aisdb
from aisdb import SQLiteDBConn, DBQuery, DomainFromPoints
from datetime import datetime

dbpath = 'YOUR_DATABASE.db'  # path to your database
start_time = datetime.strptime("2018-01-01 00:00:00", '%Y-%m-%d %H:%M:%S')
end_time = datetime.strptime("2018-01-02 00:00:00", '%Y-%m-%d %H:%M:%S')

# a 50 km radius around a point off Halifax harbor
domain = DomainFromPoints(points=[(-63.6, 44.6)], radial_distances=[50000])

with SQLiteDBConn(dbpath=dbpath) as dbconn:
    qry = DBQuery(
        dbconn=dbconn, start=start_time, end=end_time,
        xmin=domain.boundary['xmin'], xmax=domain.boundary['xmax'],
        ymin=domain.boundary['ymin'], ymax=domain.boundary['ymax'],
        callback=aisdb.database.sqlfcn_callbacks.in_time_bbox_validmmsi,
    )
    tracks = aisdb.track_gen.TrackGen(qry.gen_qry(), decimate=False)
    aisdb.write_csv(tracks, 'output_sqlite.csv')

print("All tracks have been written to output_sqlite.csv")
```
{% endcode %}

Checking the output file:

{% code lineNumbers="true" %}
```
mmsi,datetime,time,lon,lat,cog,sog,heading,rot,utc_second,maneuver,Track_ID
219014000,2018-01-01 00:44:44,1514767484,-63.53717,44.63583,322,0.0,295.0,0.0,44,0,1
219014000,2018-01-01 13:44:44,1514814284,-63.53717,44.63583,119,0.0,295.0,0.0,45,0,1
219014000,2018-01-01 17:43:03,1514829783,-63.53717,44.63583,143,0.0,295.0,0.0,15,0,1
```
{% endcode %}
{% endtab %}

{% tab title="PostgreSQL" %}
{% code title="export_postgresql.py" lineNumbers="true" %}
```python
import aisdb
from aisdb import DBQuery, DomainFromPoints
from aisdb.database.dbconn import PostgresDBConn
from datetime import datetime

domain = DomainFromPoints(points=[(-63.6, 44.6)], radial_distances=[50000])

with PostgresDBConn(
    host='localhost',          # PostgreSQL address
    port=5432,                 # PostgreSQL port
    user='your_username',      # PostgreSQL username
    password='your_password',  # PostgreSQL password
    dbname='database_name',    # database name
) as dbconn:
    qry = DBQuery(
        dbconn=dbconn,
        start=datetime(2023, 1, 1), end=datetime(2023, 1, 3),
        xmin=domain.boundary['xmin'], xmax=domain.boundary['xmax'],
        ymin=domain.boundary['ymin'], ymax=domain.boundary['ymax'],
        callback=aisdb.database.sqlfcn_callbacks.in_time_bbox_validmmsi,
    )
    tracks = aisdb.track_gen.TrackGen(qry.gen_qry(), decimate=False)
    aisdb.write_csv(tracks, 'output_postgresql.csv')

print("All tracks have been written to output_postgresql.csv")
```
{% endcode %}

Checking the output file:

{% code lineNumbers="true" %}
```
mmsi,datetime,time,lon,lat,cog,sog,heading,rot,utc_second,maneuver,Track_ID
210108000,2023-01-01 00:41:51,1672545711,-63.64500,44.68833,173,0.0,0.0,0.0,0,0,1
210108000,2023-01-01 00:44:52,1672545892,-63.64500,44.68833,208,0.0,0.0,0.0,0,0,1
210108000,2023-01-01 00:47:51,1672546071,-63.64500,44.68833,176,0.0,0.0,0.0,0,0,1
```
{% endcode %}
{% endtab %}
{% endtabs %}

`write_csv()` accepts the track generator, an output path (or an `io.BytesIO` / `SpooledTemporaryFile` buffer if you'd rather write in memory), and an optional `skipcols` list of column names to leave out, which defaults to `['label', 'in_zone']`. Internally it calls `aisdb.proc_util.tracks_csv()`, which figures out the column order from the static and dynamic fields present on the first track, appends a `datetime` column derived from the epoch `time` values, and rounds a handful of numeric fields (`lon`, `lat`, and, when present, distance and depth columns from other tutorials) to a fixed number of decimals. Each AIS message gets its own row in the CSV, with one value per dynamic field, tagged with a `Track_ID` column so you can group rows belonging to the same voyage segment back together after loading the file elsewhere.

`mmsi` and `maneuver` are static per-track values (each vessel keeps one MMSI and reports its maneuver indicator once per track vector), while `lon`, `lat`, `cog`, `sog`, `heading`, `rot`, and `utc_second` are dynamic and change with every reported position.

## Writing a Custom CSV

`write_csv()` writes every column it finds, which is usually what you want. If you'd rather control the exact set of columns yourself, iterate the tracks manually and write rows with the standard library `csv` module. Two things trip people up here, and both come from the static-versus-dynamic distinction in a track dictionary. First, `mmsi` and `maneuver` are static, so they're scalar values on the track and shouldn't be indexed. Second, `lon`, `lat`, `cog`, `sog`, `heading`, `rot`, and `utc_second` are dynamic arrays with one entry per AIS message, so they need to be indexed by position.

{% code title="custom_csv.py" lineNumbers="true" %}
```python
import csv
import aisdb
from aisdb import SQLiteDBConn, DBQuery, DomainFromPoints
from datetime import datetime

dbpath = 'YOUR_DATABASE.db'
start_time = datetime.strptime("2018-01-01 00:00:00", '%Y-%m-%d %H:%M:%S')
end_time = datetime.strptime("2018-01-02 00:00:00", '%Y-%m-%d %H:%M:%S')
domain = DomainFromPoints(points=[(-63.6, 44.6)], radial_distances=[50000])

headers = ['mmsi', 'time', 'lon', 'lat', 'cog', 'sog',
           'utc_second', 'heading', 'rot', 'maneuver']

with SQLiteDBConn(dbpath=dbpath) as dbconn, open('custom_output.csv', mode='w', newline='') as file:
    qry = DBQuery(
        dbconn=dbconn, start=start_time, end=end_time,
        xmin=domain.boundary['xmin'], xmax=domain.boundary['xmax'],
        ymin=domain.boundary['ymin'], ymax=domain.boundary['ymax'],
        callback=aisdb.database.sqlfcn_callbacks.in_time_bbox_validmmsi,
    )
    tracks = aisdb.track_gen.TrackGen(qry.gen_qry(), decimate=False)

    writer = csv.DictWriter(file, fieldnames=headers)
    writer.writeheader()

    for track in tracks:
        for i in range(len(track['time'])):
            writer.writerow({
                'mmsi': track['mmsi'],
                'time': track['time'][i],
                'lon': track['lon'][i],
                'lat': track['lat'][i],
                'cog': track['cog'][i],
                'sog': track['sog'][i],
                'utc_second': track['utc_second'][i],
                'heading': track['heading'][i],
                'rot': track['rot'][i],
                'maneuver': track['maneuver'],
            })

print("All tracks have been written to custom_output.csv")
```
{% endcode %}

If you're building rows yourself outside of `csv.DictWriter`, AISdb also exposes the two lower-level pieces `write_csv()` is built from. `aisdb.proc_util.tracks_csv(tracks, skipcols=['label', 'in_zone'])` is a generator that yields the header row followed by one row per AIS message, already column-ordered and sanitized, which you can feed to your own writer. `aisdb.proc_util.write_csv_rows(rows, pathname='output.csv', mode='a')` takes any iterable of row tuples and appends them to a file, useful when you're assembling rows from several sources before writing. Neither function is re-exported at the top level, so import them from `aisdb.proc_util` directly.
