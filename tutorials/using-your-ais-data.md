---
description: >-
  Download open-source AIS data or import your own files into AISdb, from
  a raw CSV through database loading, querying, cleaning, and processing.
icon: folder-open
---

# 🔐 Using Your AIS Data

In addition to accessing data stored on the AISdb server, you can download open-source AIS data or import your own datasets for processing and analysis using AISdb. <mark style="background-color:yellow;">This tutorial walks through the full pipeline for working with your own AIS files</mark>, from downloading a raw CSV and loading it into a database, through querying, cleaning, and processing the resulting tracks. We provide two loading examples, [_Downloading and Processing Individual Files_](using-your-ais-data.md#downloading-and-processing-individual-files), which demonstrates working with a small data sample and a SQLite database, and [_Pipeline for Bulk File Downloads and Database Integration_](using-your-ais-data.md#pipeline-for-bulk-file-downloads-and-database-integration), which outlines our approach to handling multiple data file downloads and a PostgreSQL database. From there, the tutorial covers querying your database with `DBQuery`, cleaning the resulting tracks, and processing them into a usable form.

## Data Source

U.S. vessel traffic data across user-defined geographies and periods is available at [MarineCadastre](https://hub.marinecadastre.gov/pages/vesseltraffic). This resource offers comprehensive AIS data that can be accessed for various maritime analysis purposes. We can tailor the dataset based on research needs by selecting specific regions and timeframes.

## Downloading and Processing Individual Files

In the following example, we will show how to download and process a single data file and import the data to a newly created SQLite database.

First, download the AIS data for a single day using the curl command:

{% code title="download.sh" lineNumbers="true" %}
```bash
curl -o ./data/AIS_2020_01_01.zip https://coast.noaa.gov/htdata/CMSP/AISDataHandler/2020/AIS_2020_01_01.zip
```
{% endcode %}

Then, extract the downloaded ZIP file to a specific path:

{% code title="extract.sh" lineNumbers="true" %}
```bash
unzip ./data/AIS_2020_01_01.zip -d ./data/
```
{% endcode %}

We will look at the columns in the downloaded CSV file.

{% code lineNumbers="true" %}
```python
import pandas as pd

# Read CSV file in pandas dataframe
df_ = pd.read_csv("./data/AIS_2020_01_01.csv", parse_dates=["BaseDateTime"])

print(df_.columns)
```
{% endcode %}

{% code lineNumbers="true" %}
```python
Index(['MMSI', 'BaseDateTime', 'LAT', 'LON', 'SOG', 'COG', 'Heading',
       'VesselName', 'IMO', 'CallSign', 'VesselType', 'Status',
       'Length', 'Width', 'Draft', 'Cargo', 'TransceiverClass'],
      dtype='object')
```
{% endcode %}

The required columns for AISdb have specific names and may differ from those in the imported dataset. Therefore, let's define the exact list of columns needed.

{% code lineNumbers="true" %}
```
list_of_headers_ = ["MMSI","Message_ID","Repeat_indicator","Time","Millisecond","Region","Country","Base_station","Online_data","Group_code","Sequence_ID","Channel","Data_length","Vessel_Name","Call_sign","IMO","Ship_Type","Dimension_to_Bow","Dimension_to_stern","Dimension_to_port","Dimension_to_starboard","Draught","Destination","AIS_version","Navigational_status","ROT","SOG","Accuracy","Longitude","Latitude","COG","Heading","Regional","Maneuver","RAIM_flag","Communication_flag","Communication_state","UTC_year","UTC_month","UTC_day","UTC_hour","UTC_minute","UTC_second","Fixing_device","Transmission_control","ETA_month","ETA_day","ETA_hour","ETA_minute","Sequence","Destination_ID","Retransmit_flag","Country_code","Functional_ID","Data","Destination_ID_1","Sequence_1","Destination_ID_2","Sequence_2","Destination_ID_3","Sequence_3","Destination_ID_4","Sequence_4","Altitude","Altitude_sensor","Data_terminal","Mode","Safety_text","Non-standard_bits","Name_extension","Name_extension_padding","Message_ID_1_1","Offset_1_1","Message_ID_1_2","Offset_1_2","Message_ID_2_1","Offset_2_1","Destination_ID_A","Offset_A","Increment_A","Destination_ID_B","offsetB","incrementB","data_msg_type","station_ID","Z_count","num_data_words","health","unit_flag","display","DSC","band","msg22","offset1","num_slots1","timeout1","Increment_1","Offset_2","Number_slots_2","Timeout_2","Increment_2","Offset_3","Number_slots_3","Timeout_3","Increment_3","Offset_4","Number_slots_4","Timeout_4","Increment_4","ATON_type","ATON_name","off_position","ATON_status","Virtual_ATON","Channel_A","Channel_B","Tx_Rx_mode","Power","Message_indicator","Channel_A_bandwidth","Channel_B_bandwidth","Transzone_size","Longitude_1","Latitude_1","Longitude_2","Latitude_2","Station_Type","Report_Interval","Quiet_Time","Part_Number","Vendor_ID","Mother_ship_MMSI","Destination_indicator","Binary_flag","GNSS_status","spare","spare2","spare3","spare4"]
```
{% endcode %}

Next, we update the column names in the existing dataframe `df_` and change the time format as required. The timestamp of an AIS message is represented by `BaseDateTime` in the default format `YYYY-MM-DDTHH:MM:SS`. For AISdb, however, the time is represented in UNIX format. We now read the CSV and apply the necessary changes to the date format:

{% code title="process.py" lineNumbers="true" %}
```python
# Take the first 40,000 records from the original dataframe
df = df_.iloc[0:40000]

# Create a new dataframe with the specified headers
df_new = pd.DataFrame(columns=list_of_headers_)

# Populate the new dataframe with formatted data from the original dataframe
df_new['Time'] = pd.to_datetime(df['BaseDateTime']).dt.strftime('%Y%m%d_%H%M%S')
df_new['Latitude'] = df['LAT']
df_new['Longitude'] = df['LON']
df_new['Vessel_Name'] = df['VesselName']
df_new['Call_sign'] = df['CallSign']
df_new['Ship_Type'] = df['VesselType'].fillna(0).astype(int)
df_new['Navigational_status'] = df['Status']
df_new['Draught'] = df['Draft']
df_new['Message_ID'] = 1  # Mark all messages as dynamic by default
df_new['Millisecond'] = 0

# Transfer additional columns from the original dataframe, if they exist
for col_n in df_new:
    if col_n in df.columns:
        df_new[col_n] = df[col_n]

# Extract static messages for each unique vessel
filtered_df = df_new[df_new['Ship_Type'].notnull() & (df_new['Ship_Type'] != 0)]
filtered_df = filtered_df.drop_duplicates(subset='MMSI', keep='first')
filtered_df = filtered_df.reset_index(drop=True)
filtered_df['Message_ID'] = 5  # Mark these as static messages

# Merge dynamic and static messages into a single dataframe
df_new = pd.concat([filtered_df, df_new])

# Save the final dataframe to a CSV file
# The quoting parameter is necessary because the csvreader reads each column value as a string by default
df_new.to_csv("./data/AIS_2020_01_01_aisdb.csv", index=False, quoting=1)
```
{% endcode %}

In the code, we can see that we have mapped the column names accordingly. The data type of some columns has also been changed. An nm4 file usually contains raw messages with a Message\_ID separating static messages from dynamic ones; however, the MarineCadastre data does not have such an indicator of message type. Thus, adding static messages is necessary for database creation so that a table related to metadata is created.

Let's process the CSV to create an SQLite database using the aisdb package.

{% code lineNumbers="true" %}
```python
import aisdb

# Establish a connection to the SQLite database and decode messages from the CSV file
with aisdb.SQLiteDBConn('./data/test_decode_msgs.db') as dbconn:
        aisdb.decode_msgs(filepaths=["./data/AIS_2020_01_01_aisdb.csv"],
                          dbconn=dbconn, source='Testing', verbose=True)
```
{% endcode %}

{% code lineNumbers="true" %}
```
generating file checksums...
checking file dates...
creating tables and dropping table indexes...
Memory: 20.65GB remaining.  CPUs: 12.  Average file size: 49.12MB  Spawning 4 workers
saving checksums...
processing ./data/AIS_2020_01_01_aisdb.csv
AIS_2020_01_01_aisdb.csv                                         count:   49323    elapsed:    0.27s    rate:   183129 msgs/s
cleaning temporary data...
aggregating static reports into static_202001_aggregate...
```
{% endcode %}

A SQLite database has now been created.&#x20;

{% code lineNumbers="true" %}
```bash
sqlite3 ./data/test_decode_msgs.db

sqlite> .tables
ais_202001_dynamic       coarsetype_ref           static_202001_aggregate
ais_202001_static        hashmap 
```
{% endcode %}

If you would rather load the same file into PostgreSQL, connect with `PostgresDBConn` instead of `SQLiteDBConn` and pass the same `filepaths` list to `decode_msgs`. `PostgresDBConn` accepts either a set of keyword arguments or a libpq connection string.

{% code lineNumbers="true" %}
```python
import aisdb

psql_conn_string = "postgresql://USERNAME:PASSWORD@HOST:PORT/DATABASE"

with aisdb.PostgresDBConn(libpq_connstring=psql_conn_string) as dbconn:
    aisdb.decode_msgs(filepaths=["./data/AIS_2020_01_01_aisdb.csv"],
                      dbconn=dbconn, source='Testing', verbose=True)
```
{% endcode %}

The keyword-argument form is equivalent and often easier to keep in a config file or environment variables.

{% code lineNumbers="true" %}
```python
import os
import aisdb

with aisdb.PostgresDBConn(
        host='localhost',
        port=5432,
        user='postgres',
        password=os.environ.get('POSTGRES_PASSWORD'),
        dbname='aisdb',
) as dbconn:
    aisdb.decode_msgs(filepaths=["./data/AIS_2020_01_01_aisdb.csv"],
                      dbconn=dbconn, source='Testing', verbose=True)
```
{% endcode %}

Everything downstream, querying, cleaning, and processing, works identically against a PostgreSQL connection, since `DBQuery` accepts any `SQLiteDBConn` or `PostgresDBConn` object.

## Querying Your Own Data

Once your file is decoded and sitting in a database, the loading step is done and the rest of the pipeline is the same regardless of where the data came from. Querying uses `DBQuery` to select rows by time range and location, then `TrackGen` to reshape those rows into per-vessel track dictionaries. Both classes are covered in more depth in [_Data Querying_](data-querying.md); here we apply them directly to the SQLite database created above.

{% code lineNumbers="true" %}
```python
from datetime import datetime
import aisdb

dbpath = './data/test_decode_msgs.db'

start_time = datetime(2020, 1, 1)
end_time = datetime(2020, 1, 2)

with aisdb.SQLiteDBConn(dbpath=dbpath) as dbconn:
    qry = aisdb.DBQuery(
        dbconn=dbconn,
        start=start_time,
        end=end_time,
        callback=aisdb.database.sqlfcn_callbacks.in_timerange_validmmsi,
    )
    rowgen = qry.gen_qry()
    tracks = aisdb.TrackGen(rowgen, decimate=True)

    for track in tracks:
        print(track['mmsi'], track['lon'].size)
```
{% endcode %}

`in_timerange_validmmsi` restricts the query to the given window and drops rows with a malformed MMSI, which is a sensible default when the source data has not been cleaned yet. `gen_qry()` yields rows sorted by MMSI and time, and `TrackGen` collapses those rows into one dictionary per vessel, with `decimate=True` applying linear curve decimation to drop redundant points along straight segments.

## Cleaning the Data

Data pulled from a real-world source such as MarineCadastre or your own receiver will contain some amount of noise, duplicate MMSIs, anchored vessels, and the occasional impossible jump in position. AISdb's `denoising_encoder` module handles this. The [_Data Cleaning_](data-cleaning.md) tutorial covers the module in detail; a minimal pipeline on the tracks queried above looks like this.

{% code lineNumbers="true" %}
```python
import aisdb

# Drop pings recorded at 0.5 knots or slower (anchored or moored vessels)
moving_tracks = aisdb.remove_pings_wrt_speed(tracks, speed_threshold=0.5)

# Split and re-link segments where speed or distance imply impossible jumps
clean_tracks = aisdb.encode_greatcircledistance(
    moving_tracks,
    distance_threshold=20000,  # meters
    speed_threshold=50,        # knots
    minscore=1e-6,
)
```
{% endcode %}

`remove_pings_wrt_speed()` and `encode_greatcircledistance()` both accept and return a track generator, so they chain in whatever order suits the noise in your data. Since these are generators, nothing is computed until the tracks are consumed downstream.

## Processing and Exporting

With the tracks queried and cleaned, the last step is turning them into something usable, whether that is an interpolated trajectory, a CSV file, or a map. `aisdb.interp_time()` resamples a track to a fixed time step, which is useful for aligning trajectories to a common temporal grid before further analysis.

{% code lineNumbers="true" %}
```python
from datetime import timedelta
import aisdb

interpolated_tracks = aisdb.interp_time(clean_tracks, step=timedelta(minutes=10))
```
{% endcode %}

To save the processed tracks to disk, `aisdb.write_csv()` writes each track's column vectors as rows in a CSV file.

{% code lineNumbers="true" %}
```python
import aisdb

aisdb.write_csv(interpolated_tracks, fpath='./data/processed_tracks.csv')
```
{% endcode %}

Or, to inspect the result visually instead, pass the tracks straight to `aisdb.web_interface.visualize()`, the same way earlier tutorials do.

{% code lineNumbers="true" %}
```python
import aisdb

if __name__ == '__main__':
    aisdb.web_interface.visualize(
        interpolated_tracks,
        visualearth=True,
        open_browser=True,
    )
```
{% endcode %}

That covers the full pipeline for your own AIS files, loading raw messages into a database with `decode_msgs`, querying them back out with `DBQuery` and `TrackGen`, cleaning the result with the `denoising_encoder` functions, and processing the cleaned tracks into an interpolated trajectory, a CSV export, or a visualization.

## Pipeline for Bulk File Downloads and Database Integration

This section provides an example of downloading and processing multiple files and loading the data into an AISdb-aligned database. The pipeline is packaged as the `noaa-integrator` command-line tool, available in this [GitHub repository](https://github.com/MAPS-Lab/AISdb-NOAA-Integrator). Each stage is a subcommand; run the stages you need, in order.

{% stepper %}
{% step %}
#### Install the tool

Clone the repository and sync its environment with [uv](https://docs.astral.sh/uv/):

{% code title="install.sh" lineNumbers="true" %}
```bash
git clone https://github.com/MAPS-Lab/AISdb-NOAA-Integrator
cd NOAA-Integrator
uv sync --extra load
```
{% endcode %}
{% endstep %}

{% step %}
#### AIS Data Download and Extraction

The `download` stage fetches AIS archives from [MarineCadastre](https://hub.marinecadastre.gov/pages/vesseltraffic) for the years you specify, the `organize` stage groups them into `{year}{month}` folders, and the `extract` stage decompresses them. All NOAA formats are handled, including daily ZIP archives (2015-2024) and Zstandard-compressed CSV (2025 onward).

{% code title="download_extract.sh" lineNumbers="true" %}
```bash
uv run noaa-integrator download --start-year 2023 --end-year 2023 --dest data/downloads
uv run noaa-integrator organize --base-dir data/downloads
uv run noaa-integrator extract --base-dir data/downloads --dest data/extracted
```
{% endcode %}
{% endstep %}

{% step %}
#### Preprocessing - Geographic Filtering and Deduplication

The optional `filter` stage keeps only records inside a geographic bounding box, and the `dedup` stage removes duplicate rows, retaining unique AIS messages:

{% code title="filter_dedup.sh" lineNumbers="true" %}
```bash
uv run noaa-integrator filter \
    --base-dir data/extracted --dest data/filtered \
    --start-year 2023 --end-year 2023 \
    --min-lon -77.36 --min-lat 36.02 --max-lon -57.62 --max-lat 48.64
uv run noaa-integrator dedup --directory data/filtered/202301
```
{% endcode %}
{% endstep %}

{% step %}
#### Database Loading

The `load` stage decodes the CSV files into an AISdb database through `aisdb.decode_msgs`, one month batch at a time, with automatic retries for failed batches. Both SQLite and PostgreSQL targets are supported; PostgreSQL credentials come from the `--dsn` argument or the `NOAA_PG_DSN` environment variable:

{% code title="load.sh" lineNumbers="true" %}
```bash
# SQLite
uv run noaa-integrator load --source-dir data/filtered \
    --start-year 2023 --end-year 2023 --sqlite marine_cadastre.db

# PostgreSQL / TimescaleDB
export NOAA_PG_DSN='postgresql://USERNAME:PASSWORD@localhost:5432/DBNAME'
uv run noaa-integrator load --source-dir data/filtered \
    --start-year 2023 --end-year 2023 --dsn --timescaledb
```
{% endcode %}
{% endstep %}

{% step %}
#### Query the loaded data

Once loading finishes, the data is queryable with the standard AISdb interfaces (`DBQuery`, `TrackGen`) shown earlier in this tutorial, or directly with `psql`:

{% code title="query.sh" lineNumbers="true" %}
```bash
psql -U USERNAME -d DBNAME -h localhost -p 5432
```
{% endcode %}
{% endstep %}
{% endstepper %}
