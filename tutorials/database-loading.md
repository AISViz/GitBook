---
description: >-
  Load AIS data into a SQLite or PostgreSQL database with AISdb, from
  installation through a full-year Spire ingestion example.
icon: download
---

# 📥 Database Loading

This tutorial will guide you in using the <mark style="background-color:yellow;">**AISdb**</mark> package to load AIS data into a database and perform queries. We will begin with **AISdb** installation and environment setup, then proceed to examples of querying the loaded data and creating simple visualizations.

## Install Requirements <a href="#id-1.-install-requirements" id="id-1.-install-requirements"></a>

Preparing a Python virtual environment for AISdb is a good practice. It allows you to manage dependencies and prevent conflicts with other projects, ensuring a clean and isolated setup for your work with AISdb. Run these commands in your terminal based on the operating system you are using:

{% code title="Linux" lineNumbers="true" %}
```bash
python -m venv AISdb         # create a python virtual environment
source ./AISdb/bin/activate  # activate the virtual environment
pip install aisdb            # from https://pypi.org/project/aisdb/
```
{% endcode %}

{% code title="Windows" lineNumbers="true" %}
```sh
python -m venv AISdb         # create a virtual environment
./AISdb/Scripts/activate     # activate the virtual environment
pip install aisdb            # install the AISdb package using pip
```
{% endcode %}

Now you can check your installation by running:

{% code lineNumbers="true" %}
```bash
$ python
>>> import aisdb
>>> aisdb.__version__        # '1.8.0-alpha' when built from source, or the latest PyPI release
```
{% endcode %}

If you're using AISdb in a [Jupyter](https://jupyter.org/) Notebook, please include the following commands in your notebook cells:

{% code lineNumbers="true" %}
```bash
# install nest-asyncio for enabling asyncio.run() in Jupyter Notebook
%pip install nest-asyncio

# Some of the systems may show the following error when running the user interface:
# urllib3 v2.0 only supports OpenSSL 1.1.1+; currently, the 'SSL' module is compiled with 'LibreSSL 2.8.3'.
# install urllib3 v1.26.6 to avoid this error
%pip install urllib3==1.26.6
```
{% endcode %}

Then, import the required packages:

{% code lineNumbers="true" %}
```python
from datetime import datetime, timedelta
import os
import aisdb
import nest_asyncio
nest_asyncio.apply()
```
{% endcode %}

## Load AIS data into a database <a href="#id-2.-load-ais-data-into-a-database" id="id-2.-load-ais-data-into-a-database"></a>

This section will show you how to efficiently load AIS data into a database.&#x20;

AISdb includes two database connection approaches:&#x20;

1. SQLite database connection; and,
2. PostgreSQL database connection.

{% tabs %}
{% tab title="SQLite" %}
We work with the SQLite database in most usage scenarios. Here is an example of loading data using the sample data included in the AISdb package:

<pre class="language-python" data-line-numbers><code class="lang-python"># List the test data files included in the package
print(os.listdir(os.path.join(aisdb.sqlpath, '..', 'tests', 'testdata')))
# You will see files such as:
# ['test_data_20210701.csv', 'test_data_20211101.nm4', 'test_data_20211101.nm4.gz',
#  'test_data_20211101.nm4.zip', 'test_data_201201.nmea', 'test_data_noaa_20230101.csv']

# Set the path for the SQLite database file to be used
dbpath = './test_database.db'

# Use test_data_20210701.csv as the test data
filepaths = [os.path.join(aisdb.sqlpath, '..', 'tests', 'testdata', 'test_data_20210701.csv')]
with aisdb.SQLiteDBConn(dbpath=dbpath) as dbconn:
    aisdb.decode_msgs(filepaths=filepaths, dbconn=dbconn, source='TESTING')
</code></pre>

The code above decodes the AIS messages from the CSV file specified in `filepaths` and inserts them into the SQLite database connected via `dbconn`.&#x20;

The following is a quick example of a **query** and **visualization** of the data we just loaded with AISdb:

{% code lineNumbers="true" %}
```python
start_time = datetime.strptime("2021-07-01 00:00:00", '%Y-%m-%d %H:%M:%S')
end_time = datetime.strptime("2021-07-02 00:00:00", '%Y-%m-%d %H:%M:%S')

with aisdb.SQLiteDBConn(dbpath=dbpath) as dbconn:
    qry = aisdb.DBQuery(
        dbconn=dbconn,
        callback=aisdb.database.sqlfcn_callbacks.in_timerange_validmmsi,
        start=start_time,
        end=end_time,
    )
    rowgen = qry.gen_qry()
    tracks = aisdb.track_gen.TrackGen(rowgen, decimate=False)

    if __name__ == '__main__':
        aisdb.web_interface.visualize(
            tracks,
            visualearth=True,
            open_browser=True,
        )
```
{% endcode %}

<figure><img src="../.gitbook/assets/image (17).png" alt=""><figcaption><p>Visualization of vessel tracks queried from SQLite database created from test data</p></figcaption></figure>
{% endtab %}

{% tab title="PostgreSQL" %}
In addition to SQLite, AISdb supports PostgreSQL, which handles concurrent access and data sharing better than SQLite and scales more comfortably to larger, collaborative deployments. `psycopg` (the PostgreSQL driver AISdb uses under the hood) ships as a core dependency, so `pip install aisdb` already gives you everything you need, no separate driver install required.

To connect to a PostgreSQL database, AISdb uses the `PostgresDBConn` class:

{% code lineNumbers="true" %}
```python
from aisdb.database.dbconn import PostgresDBConn

# Option 1: Using keyword arguments
dbconn = PostgresDBConn(
    hostaddr='127.0.0.1',      # Replace with the PostgreSQL address
    port=5432,                 # Replace with the PostgreSQL running port
    user='USERNAME',           # Replace with the PostgreSQL username
    password='PASSWORD',       # Replace with your password
    dbname='aisviz'            # Replace with your database name
)

# Option 2: Using a connection string
dbconn = PostgresDBConn('postgresql://USERNAME:PASSWORD@HOST:PORT/DATABASE')
```
{% endcode %}

After you open a connection to PostgreSQL and point `aisdb.decode_msgs` at your data files, it runs through file parsing, table creation, data insertion, and index rebuilding, in that order.

Please pay close attention to the arguments of `aisdb.decode_msgs`, since they control how files are parsed, how fast the load runs, and which table layout gets used. The full signature is `decode_msgs(filepaths, dbconn, source, vacuum=False, skip_checksum=True, workers=4, type_preference="all", raw_insertion=True, verbose=True, timescaledb=False)`. The parameters worth understanding before a large load are:

* **`source`** _(str, required)_\
  A free-form label identifying where the data came from, stored alongside each decoded message (for example `"Spire"`, `"NOAA"`, or `"TESTING"`). There is no default; you must always pass one. If the string contains `"noaa"` (case-insensitive), AISdb switches to parsing NOAA's `BaseDateTime` CSV column instead of the generic `Time` column.
* **`workers`** _(int, optional)_
  * Number of parallel worker processes used to decode files.
  * **Default**: `4`.
* **`type_preference`** _(str, optional)_
  * Which AIS message types to keep during decoding (`"all"`, `"static"`, or `"dynamic"`).
  * **Default**: `"all"`.
* **`raw_insertion`** _(bool, optional)_
  * If `True`, rows are inserted without maintaining indexes as you go, which is significantly faster for bulk loads. Indexes get (re)built afterward. Set to `False` only for small, incremental inserts into an already-indexed table.
  * **Default**: `True`.
* **`skip_checksum`** _(bool, optional)_
  * If `True`, skips the MD5 checksum lookup AISdb otherwise uses to avoid re-ingesting a file it has already processed.
  * **Default**: `True`.
* **`vacuum`** _(bool, optional)_
  * If `True`, runs a `VACUUM` on the database after insertion to reclaim space and update planner statistics.
  * **Default**: `False`.
* **`timescaledb`** _(bool, optional)_
  * Set to `True` **only if** using the TimescaleDB extension in your PostgreSQL database, which structures dynamic tables as hypertables instead of the original per-month **B-Tree indexed** tables.
  * **Default**: `False`. Refer to the [TimescaleDB documentation](https://docs.timescale.com/self-hosted/latest/) for proper setup and usage.
{% endtab %}
{% endtabs %}

### Example: Processing a Full Year of Spire Data (2024)

The following example demonstrates how to process and load Spire data for the entire year 2024 into an `aisdb` database with the TimescaleDB extension installed:

{% code title="spire_year_ingest.py" lineNumbers="true" %}
```python
import time

psql_conn_string = 'postgresql://USERNAME:PASSWORD@HOST:PORT/DATABASE'

start_year = 2024
end_year = 2024
start_month = 1
end_month = 12

overall_start_time = time.time()

for year in range(start_year, end_year + 1):
    for month in range(start_month, end_month + 1):
        print(f'Loading {year}{month:02d}')
        month_start_time = time.time()

        filepaths = aisdb.glob_files(f'/slow-array/Spire/{year}{month:02d}/','.zip')
        filepaths = sorted([f for f in filepaths if f'{year}{month:02d}' in f])
        print(f'Number of files: {len(filepaths)}')

        with aisdb.PostgresDBConn(libpq_connstring=psql_conn_string) as dbconn:
            try:
                aisdb.decode_msgs(filepaths,
                                dbconn=dbconn,
                                source='Spire',
                                verbose=True,
                                skip_checksum=True,
                                raw_insertion=True,
                                workers=6,
                                timescaledb=True,
                        )
            except Exception as e:
                print(f'Error loading {year}{month:02d}: {e}')
                continue
```
{% endcode %}

Example of performing queries and visualizations with PostgreSQL database:

{% code lineNumbers="true" %}
```python
from datetime import datetime
import aisdb
from aisdb.gis import DomainFromPoints

# Define a spatial domain centered around the point (-63.6, 44.6) with a radial distance of 50000 meters.
domain = DomainFromPoints(points=[(-63.6, 44.6)], radial_distances=[50000])

with aisdb.PostgresDBConn(libpq_connstring=psql_conn_string) as dbconn:
    # Create a query object to fetch AIS data within the specified time range and spatial domain.
    qry = aisdb.DBQuery(
        dbconn=dbconn,
        start=datetime(2023, 1, 1), end=datetime(2023, 2, 1),
        xmin=domain.boundary['xmin'], xmax=domain.boundary['xmax'],
        ymin=domain.boundary['ymin'], ymax=domain.boundary['ymax'],
        callback=aisdb.database.sqlfcn_callbacks.in_time_bbox_validmmsi
    )

    # Generate rows from the query
    rowgen = qry.gen_qry()

    # Convert the generated rows into tracks
    tracks = aisdb.track_gen.TrackGen(rowgen, decimate=False)

    # Visualize the tracks on a map
    aisdb.web_interface.visualize(
        tracks,           # The tracks (trajectories) to visualize.
        domain=domain,    # The spatial domain to use for the visualization.
        visualearth=True, # If True, use Visual Earth for the map background.
        open_browser=True # If True, automatically open the visualization in a web browser.
    )
```
{% endcode %}

<figure><img src="../.gitbook/assets/Screenshot from 2024-09-04 11-09-25.png" alt=""><figcaption><p>Visualization of tracks queried from PostgreSQL database</p></figcaption></figure>

If you want to load your own AIS data instead of the bundled test files, see our guide on data processing and database creation, [_Using Your AIS Data_](using-your-ais-data.md)_._
