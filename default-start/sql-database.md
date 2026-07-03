---
description: How AISdb organizes decoded AIS messages across SQLite and PostgreSQL/TimescaleDB tables, and how to query them directly with SQL.
icon: database
cover: >-
  https://images.unsplash.com/photo-1544383835-bda2bc66a55d?crop=entropy&cs=srgb&fm=jpg&ixid=M3wxOTcwMjR8MHwxfHNlYXJjaHwzfHxkYXRhYmFzZXxlbnwwfHx8fDE3MjMyNjIyOTJ8MA&ixlib=rb-4.0.3&q=85
coverY: 47.15
---

# 🗄️ SQL Database

AISdb stores decoded AIS messages in a relational database rather than flat files, which is what makes range queries, joins across message types, and multi-year aggregations practical. Two backends are supported. SQLite is the default for local work, a single-file database that needs no server and is easy to copy or drop into version control for small projects. PostgreSQL is the option for shared or production deployments, and it can optionally run on top of TimescaleDB for large, high-ingest-rate collections. Both backends expose the same table layout and the same `DBQuery`/`TrackGen` query interface, so switching between them later mostly means swapping the connection object.

### Choosing a Database Backend

Every AISdb database connection is opened through one of two classes in `aisdb.database.dbconn`, both of which subclass a shared `DBConn` base and both of which support the context manager protocol (`with ... as dbconn:`).

`SQLiteDBConn` wraps a `sqlite3.Connection` and only needs a filesystem path. If the file does not exist yet, it will be created the first time you decode messages into it.

{% code lineNumbers="true" %}
```python
from aisdb import SQLiteDBConn

dbpath = "AIS.db"

with SQLiteDBConn(dbpath) as dbconn:
    # decode_msgs, DBQuery, and custom SQL all use this connection
    ...
```
{% endcode %}

`PostgresDBConn` wraps a `psycopg` connection and accepts either a `libpq` connection string or individual keyword arguments (`host`, `port`, `user`, `dbname`, `password`, and any other keyword recognized by [libpq](https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-PARAMKEYWORDS)).

{% code lineNumbers="true" %}
```python
import os
from aisdb import PostgresDBConn

# Option 1: keyword arguments
with PostgresDBConn(
    host="127.0.0.1",
    port=5432,
    user="postgres",
    dbname="postgres",
    password=os.environ.get("POSTGRES_PASSWORD"),
) as dbconn:
    ...

# Option 2: a libpq connection string
with PostgresDBConn(libpq_connstring="postgresql://localhost:5432/postgres") as dbconn:
    ...
```
{% endcode %}

Pick SQLite for quick exploration on your own machine, and PostgreSQL when several people or processes need to read and write the same database, when the collection grows past what a single SQLite file handles comfortably, or when you plan to enable TimescaleDB (see below). Regardless of the backend, [`decode_msgs`](quick-start.md) accepts either connection type as its `dbconn` argument, and the same `DBQuery`/`TrackGen` code works unchanged against both.

### Table Naming

When loading data into the database, messages are sorted into SQL tables determined by the message type and month. The table names follow this format, where `{YYYYMM}` is the four-digit year and two-digit month.

{% code lineNumbers="true" %}
```
ais_{YYYYMM}_static  # table with static AIS messages
ais_{YYYYMM}_dynamic # table with dynamic AIS message
```
{% endcode %}

Some additional tables containing computed data may be created depending on the indexes used. Examples include an aggregate of vessel static data by month and a virtual table used as a covering index.&#x20;

{% code lineNumbers="true" %}
```
static_{YYYYMM}_aggregate # table of aggregated static vessel data
```
{% endcode %}

Additional tables are also included for storing data not directly derived from AIS message reports.

{% code lineNumbers="true" %}
```
coarsetype_ref # a reference table that maps numeric ship type codes to their descriptions
```
{% endcode %}

For quick reference to data types and detailed explanations of these table entries, please see the [Detailed Table Description](sql-database.md#detailed-table-description).

### Custom SQL Queries

In addition to querying the database using the [`DBQuery`](https://aisviz.cs.dal.ca/AISdb/api/aisdb.database.dbqry.html) module, there is an option to customize the query with your own SQL code. The examples below connect directly with `sqlite3`, which works against an SQLite database file. Against PostgreSQL, swap `sqlite3.connect(dbpath)` for `psycopg.connect(...)` (or reuse the connection already opened through `aisdb.PostgresDBConn`) and the same SQL runs unchanged, since both backends share identical table and column names.

Example of listing all the tables in your database:

{% code lineNumbers="true" %}
```python
import sqlite3

dbpath='YOUR_DATABASE.db' # Define the path to your database

# Connect to the database
connection = sqlite3.connect(dbpath)

# Create a cursor object
cursor = connection.cursor()

# Query to list all tables
query = "SELECT name FROM sqlite_master WHERE type='table';"
cursor.execute(query)

# Fetch the results
tables = cursor.fetchall()

# Print the names of the tables
print("Tables in the database:")
for table in tables:
    print(table[0])

# Close the connection
connection.close()
```
{% endcode %}

As messages are separated into tables by message type and month, queries spanning multiple message types or months should use UNIONs and JOINs to combine results as appropriate.&#x20;

Example of querying tables with `JOIN`:

{% code lineNumbers="true" %}
```python
import sqlite3

# Connect to the database
connection = sqlite3.connect('YOUR_DATABASE.db')

# Create a cursor object
cursor = connection.cursor()

# The table suffix for the month you want to query, format YYYYMM
year_month = '202401'

# Define the JOIN SQL query
query = f"""
SELECT
    d.mmsi, 
    d.time,
    d.longitude,
    d.latitude,
    d.sog,
    d.cog,
    s.vessel_name,
    s.ship_type
FROM ais_{year_month}_dynamic d
LEFT JOIN ais_{year_month}_static s ON d.mmsi = s.mmsi
WHERE d.time BETWEEN 1707033659 AND 1708176856  -- Filter by time range
  AND d.longitude BETWEEN -68 AND -56           -- Filter by geographical area
  AND d.latitude BETWEEN 45 AND 51.5;
"""

# Execute the query
cursor.execute(query)

# Fetch the results
results = cursor.fetchall()

# Print the results
for row in results:
    print(row)

# Close the connection
connection.close()
```
{% endcode %}

Each row in `results` is a plain tuple, one element per selected column, in the order listed in the `SELECT`. A row from the query above looks like this.

{% code lineNumbers="true" %}
```
(258123456, 1707033721, -63.5721, 44.6488, 12.4, 187.3, 'ATLANTIC CARRIER', 70)
```
{% endcode %}

The exact rows you see depend on what is in your database. Rows come back in whatever order SQLite returns them unless you add an `ORDER BY` clause, and `vessel_name`/`ship_type` will be `None` for any MMSI with no matching row in the static table (since the query uses a `LEFT JOIN`).

More information about SQL queries can be found in [online tutorials](https://sqlbolt.com/).

The `ais_{YYYYMM}_dynamic` tables are created with a composite primary key over `(mmsi, time, longitude, latitude, sog, cog, source)` on SQLite, which acts as a covering index for the queries `DBQuery` generates. Filtering on a narrow range of MMSIs, timestamps, longitudes, and latitudes lets SQLite satisfy most of the query directly from that index, so query performance improves the more you narrow those bounds. Broad, unbounded queries will scan a much larger share of the table and will not benefit as much. If you need custom indexes for a specific manual query, define them directly on the monthly `ais_{YYYYMM}_dynamic` and `ais_{YYYYMM}_static` tables rather than trying to add a separate index structure alongside them.

Timestamps are stored as epoch seconds in the database (seconds since 1970-01-01 UTC), matching the `time` column described in the [Detailed Table Description](sql-database.md#detailed-table-description). To facilitate querying the database manually, use the `dt_2_epoch()` function to convert datetime values to epoch seconds and the `epoch_2_dt()` function to convert epoch seconds back to datetime values. Here is how you can use `dt_2_epoch()` with the example above:

{% code lineNumbers="true" %}
```python
import sqlite3
from datetime import datetime
from aisdb.gis import dt_2_epoch

# Define the datetime range
start_datetime = datetime(2018, 1, 1, 0, 0, 0)
end_datetime = datetime(2018, 1, 1, 1, 59, 59)

# Convert datetime to epoch time
start_epoch = dt_2_epoch(start_datetime)
end_epoch = dt_2_epoch(end_datetime)

# Connect to the database
connection = sqlite3.connect('YOUR_DATABASE.db')

# Create a cursor object
cursor = connection.cursor()

# Define the JOIN SQL query using an epoch time range
query = f"""
SELECT
    d.mmsi, 
    d.time,
    d.longitude,
    d.latitude,
    d.sog,
    d.cog,
    s.vessel_name,
    s.ship_type
FROM ais_201801_dynamic d
LEFT JOIN ais_201801_static s ON d.mmsi = s.mmsi
WHERE d.time BETWEEN {start_epoch} AND {end_epoch}  -- Filter by time range
  AND d.longitude BETWEEN -68 AND -56           -- Filter by geographical area
  AND d.latitude BETWEEN 45 AND 51.5;
"""

# Execute the query
cursor.execute(query)

# Fetch the results
results = cursor.fetchall()

# Print the results
for row in results:
    print(row)

# Close the connection
connection.close()
```
{% endcode %}

For more examples, please see the SQL code in [`aisdb_sql/`](https://github.com/MAPS-Lab/AISdb/tree/master/aisdb/aisdb_sql) that is used to create database tables and associated queries.

### Optional TimescaleDB Backend

[TimescaleDB](https://www.timescale.com/) is a PostgreSQL extension for time-series data, and AISdb can use it in place of the plain PostgreSQL table layout described above. It is entirely optional. If your PostgreSQL server has the extension installed, opt in when decoding messages by passing `timescaledb=True` to [`decode_msgs`](quick-start.md):

{% code lineNumbers="true" %}
```python
from aisdb import PostgresDBConn, decode_msgs

filepaths = ["ais_data.nm4"]

with PostgresDBConn(
    host="127.0.0.1",
    port=5432,
    user="postgres",
    dbname="postgres",
    password="YOUR_PASSWORD",
) as dbconn:
    decode_msgs(
        filepaths=filepaths,
        dbconn=dbconn,
        source="TimescaleExample",
        verbose=True,
        timescaledb=True,
    )
```
{% endcode %}

With `timescaledb=True`, AISdb creates the monthly `ais_{YYYYMM}_dynamic` and `ais_{YYYYMM}_static` tables as [hypertables](https://docs.timescale.com/use-timescale/latest/hypertables/) partitioned on `time` (and space-partitioned on `mmsi`), rather than as plain PostgreSQL tables. This is what lets TimescaleDB spread the ingest and query workload for a large, continuously growing AIS collection across many chunks instead of one ever-larger table. The column layout is identical to the plain PostgreSQL schema, so `DBQuery`, custom SQL, and everything else on this page works the same way regardless of whether TimescaleDB is enabled underneath.

`PostgresDBConn` also exposes a few maintenance methods that are aware of the `timescaledb` flag, useful when you are managing indexes or cleaning up a bulk ingest by hand.

{% code lineNumbers="true" %}
```python
month = "202401"  # table suffix, format YYYYMM

with PostgresDBConn(hostaddr="127.0.0.1", port=5432, user="postgres", dbname="postgres") as dbconn:
    # Drop the mmsi/time indexes before a large bulk load
    dbconn.drop_indexes(month, timescaledb=True)

    # ... run decode_msgs or bulk insertion here ...

    # Remove duplicate dynamic (position report) rows for the month
    dbconn.deduplicate_dynamic_msgs(month)

    # Rebuild the mmsi/time indexes once loading is complete
    dbconn.rebuild_indexes(month, timescaledb=True)
```
{% endcode %}

Dropping the indexes before a large bulk insert and rebuilding them afterward is significantly faster than maintaining the indexes row by row during the insert. Pass `timescaledb=False` (the default) for these same methods against a plain PostgreSQL database, which manages indexes named `idx_{YYYYMM}_dynamic_mmsi`, `idx_{YYYYMM}_dynamic_time`, `idx_{YYYYMM}_dynamic_longitude`, and `idx_{YYYYMM}_dynamic_latitude` instead of the two combined TimescaleDB indexes.

### Detailed Table Description

<details>
<summary><code>ais_{YYYYMM}_dynamic</code> tables</summary>

<table><thead><tr><th width="202">Column</th><th width="157">Data Type</th><th>Description</th></tr></thead><tbody><tr><td><code>mmsi</code></td><td><code>INTEGER</code></td><td>Maritime Mobile Service Identity, a unique identifier for vessels.</td></tr><tr><td><code>time</code></td><td><code>INTEGER</code></td><td>Timestamp of the AIS message, in epoch seconds.</td></tr><tr><td><code>longitude</code></td><td><code>REAL</code></td><td>Longitude of the vessel in decimal degrees.</td></tr><tr><td><code>latitude</code></td><td><code>REAL</code></td><td>Latitude of the vessel in decimal degrees.</td></tr><tr><td><code>rot</code></td><td><code>REAL</code></td><td>Rate of turn, indicating how fast the vessel is turning.</td></tr><tr><td><code>sog</code></td><td><code>REAL</code></td><td>Speed over ground, in knots.</td></tr><tr><td><code>cog</code></td><td><code>REAL</code></td><td>Course over ground, in degrees.</td></tr><tr><td><code>heading</code></td><td><code>REAL</code></td><td>Heading of the vessel, in degrees.</td></tr><tr><td><code>maneuver</code></td><td><code>BOOLEAN</code></td><td>Indicator for whether the vessel is performing a special maneuver.</td></tr><tr><td><code>utc_second</code></td><td><code>INTEGER</code></td><td>Second of the UTC timestamp when the message was generated.</td></tr><tr><td><code>source</code></td><td><code>TEXT</code></td><td>Source of the AIS data.</td></tr></tbody></table>

</details>

<details>
<summary><code>ais_{YYYYMM}_static</code> tables</summary>

<table><thead><tr><th width="205">Column</th><th width="157">Data Type</th><th>Description</th></tr></thead><tbody><tr><td><code>mmsi</code></td><td><code>INTEGER</code></td><td>Maritime Mobile Service Identity, a unique identifier for vessels.</td></tr><tr><td><code>time</code></td><td><code>INTEGER</code></td><td>Timestamp of the AIS message, in epoch seconds.</td></tr><tr><td><code>vessel_name</code></td><td><code>TEXT</code></td><td>Name of the vessel.</td></tr><tr><td><code>ship_type</code></td><td><code>INTEGER</code></td><td>Numeric code representing the type of ship.</td></tr><tr><td><code>call_sign</code></td><td><code>TEXT</code></td><td>International radio call sign of the vessel.</td></tr><tr><td><code>imo</code></td><td><code>INTEGER</code></td><td>International Maritime Organization number, another unique vessel identifier.</td></tr><tr><td><code>dim_bow</code></td><td><code>INTEGER</code></td><td>Distance from the AIS transmitter to the bow (front) of the vessel.</td></tr><tr><td><code>dim_stern</code></td><td><code>INTEGER</code></td><td>Distance from the AIS transmitter to the stern (back) of the vessel.</td></tr><tr><td><code>dim_port</code></td><td><code>INTEGER</code></td><td>Distance from the AIS transmitter to the port (left) side of the vessel.</td></tr><tr><td><code>dim_star</code></td><td><code>INTEGER</code></td><td>Distance from the AIS transmitter to the starboard (right) side of the vessel.</td></tr><tr><td><code>draught</code></td><td><code>REAL</code></td><td>Maximum depth of the vessel's hull below the waterline, in meters.</td></tr><tr><td><code>destination</code></td><td><code>TEXT</code></td><td>Destination port or location where the vessel is heading.</td></tr><tr><td><code>ais_version</code></td><td><code>INTEGER</code></td><td>AIS protocol version used by the vessel.</td></tr><tr><td><code>fixing_device</code></td><td><code>TEXT</code></td><td>Type of device used for fixing the vessel's position (e.g., GPS).</td></tr><tr><td><code>eta_month</code></td><td><code>INTEGER</code></td><td>Estimated time of arrival month.</td></tr><tr><td><code>eta_day</code></td><td><code>INTEGER</code></td><td>Estimated time of arrival day.</td></tr><tr><td><code>eta_hour</code></td><td><code>INTEGER</code></td><td>Estimated time of arrival hour.</td></tr><tr><td><code>eta_minute</code></td><td><code>INTEGER</code></td><td>Estimated time of arrival minute.</td></tr><tr><td><code>source</code></td><td><code>TEXT</code></td><td>Source of the AIS data (e.g., specific AIS receiver or data provider).</td></tr></tbody></table>

</details>

<details>
<summary><code>static_{YYYYMM}_aggregate</code> tables</summary>

<table><thead><tr><th width="206">Column</th><th width="157">Data Type</th><th>Description</th></tr></thead><tbody><tr><td><code>mmsi</code></td><td><code>INTEGER</code></td><td>Maritime Mobile Service Identity, a unique identifier for vessels.</td></tr><tr><td><code>imo</code></td><td><code>INTEGER</code></td><td>International Maritime Organization number, another unique vessel identifier.</td></tr><tr><td><code>vessel_name</code></td><td><code>TEXT</code></td><td>Name of the vessel.</td></tr><tr><td><code>ship_type</code></td><td><code>INTEGER</code></td><td>Numeric code representing the type of ship.</td></tr><tr><td><code>call_sign</code></td><td><code>TEXT</code></td><td>International radio call sign of the vessel.</td></tr><tr><td><code>dim_bow</code></td><td><code>INTEGER</code></td><td>Distance from the AIS transmitter to the bow (front) of the vessel.</td></tr><tr><td><code>dim_stern</code></td><td><code>INTEGER</code></td><td>Distance from the AIS transmitter to the stern (back) of the vessel.</td></tr><tr><td><code>dim_port</code></td><td><code>INTEGER</code></td><td>Distance from the AIS transmitter to the port (left) side of the vessel.</td></tr><tr><td><code>dim_star</code></td><td><code>INTEGER</code></td><td>Distance from the AIS transmitter to the starboard (right) side of the vessel.</td></tr><tr><td><code>draught</code></td><td><code>REAL</code></td><td>Maximum depth of the vessel's hull below the waterline, in meters.</td></tr><tr><td><code>destination</code></td><td><code>TEXT</code></td><td>Destination port or location where the vessel is heading.</td></tr><tr><td><code>eta_month</code></td><td><code>INTEGER</code></td><td>Estimated time of arrival month.</td></tr><tr><td><code>eta_day</code></td><td><code>INTEGER</code></td><td>Estimated time of arrival day.</td></tr><tr><td><code>eta_hour</code></td><td><code>INTEGER</code></td><td>Estimated time of arrival hour.</td></tr><tr><td><code>eta_minute</code></td><td><code>INTEGER</code></td><td>Estimated time of arrival minute.</td></tr></tbody></table>

</details>

### Where to go next

The [database loading](../tutorials/database-loading.md) tutorial walks through decoding raw AIS messages into these tables from scratch, and the [data querying](../tutorials/data-querying.md) tutorial covers `DBQuery` and `TrackGen` in more depth than the quick reference above. Reach for the custom SQL approach on this page when you need a query shape those two interfaces do not support directly.
