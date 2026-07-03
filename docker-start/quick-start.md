---
icon: docker
description: Run AISdb from the published Docker image without setting up a local Rust and Python toolchain.
hidden: true
---

# 🛰️ Quick Start

### Python Docker Quick Start

For most users, the recommended way to install AISdb is `pip install aisdb` (see the [Default Start](../default-start/quick-start.md)). Docker is useful when you'd rather not set up a local Rust and Python toolchain, or when you want a disposable environment for testing. The `meridiancfi/aisdb` image ships AISdb pre-installed on a `python:slim` base. To use it, make sure `docker` is installed, then run.

{% code title="terminal" %}
```bash
docker pull meridiancfi/aisdb
docker run --interactive --tty --volume ./:/aisdb/ meridiancfi/aisdb
```
{% endcode %}

The current working directory is mounted inside the container at `/aisdb`, so any script or notebook you drop there is visible from the container's Python interpreter. From inside the container, verify the install the same way you would locally.

```bash
python -c "import aisdb; print(aisdb.__version__)"
```

If you're building AISdb from source rather than pulling the published image, the package is compiled from Rust and Python with [Maturin](https://www.maturin.rs/), as described in the [Default Start](../default-start/quick-start.md#development-installation). Building inside a [manylinux](https://github.com/pypa/manylinux) container is the standard way to produce a wheel that's portable across Linux distributions, using the same `maturin develop --release` step you'd run locally.

### AISdb's Service Components

Beyond the Python package, AISdb includes a small set of Rust and JavaScript services for running a self-hosted deployment: an AIS `receiver`, a `database_server` that serves vectorized tracks over WebSocket, and a JavaScript/WebAssembly map front end in `aisdb_web`. These live in the [AISdb repository](https://github.com/MAPS-Lab/AISdb) alongside the Python package, each in its own top-level folder, and share a PostgreSQL database for storage.

There's currently no published `docker-compose.yml` for orchestrating all of these at once. To run them, follow the [Detailed Start](detailed-start.md) guide, which walks through building and starting each service natively with `cargo` and `npm`. The subsections below cover the two things you'll most often want without standing up the full stack: querying a PostgreSQL database directly from Python, and querying vessel tracks from a running `database_server` (including the public MERIDIAN instance) over its WebSocket API.

### Environment

Each service reads its configuration from environment variables rather than a config file. The variables below cover the common cases. Set only the ones relevant to what you're running.

{% code title=".env" lineNumbers="true" %}
```bash
# Front end (aisdb_web, bundled with Vite)

# Hostname of the database server the front end connects to
VITE_AISDBHOST='127.0.0.1'

# Port used for the database server WebSocket connection
VITE_AISDBPORT=9924

# Disable SSL/TLS for the database and livestream connections during local
# development, where the front end talks to plain ws:// instead of wss://
VITE_DISABLE_SSL_DB=1
VITE_DISABLE_STREAM=1

# Use Bing Maps tiles instead of OpenStreetMap, and set the tile server host
VITE_BINGMAPTILES=1
VITE_TILESERVER='dev.virtualearth.net'

# database_server (Rust)

# Postgres connection details read via a .pgpass file
PGPASSFILE=$HOME/.pgpass
PGUSER='postgres'
PGHOST='127.0.0.1'
PGPORT=5432

# Port the database server listens on for incoming WebSocket queries
AISDBPORT=9924

# receiver (Rust) and Python examples that talk to a live database server
AISDBHOST='127.0.0.1'
```
{% endcode %}

### Interacting with a PostgreSQL Database

PostgreSQL is preferable to SQLite when you need better write concurrency or you're running a long-lived receiver that ingests data continuously. It costs more in disk space and setup than SQLite, which is why the Default Start guide uses SQLite for the introductory examples. The easiest way to get a PostgreSQL server running for local testing is the official image.

```bash
docker run --name aisdb-postgres --env POSTGRES_PASSWORD=example \
  --publish 5432:5432 --detach postgres
```

#### Python API

`aisdb.database.dbconn.PostgresDBConn` is a drop-in replacement for `aisdb.database.dbconn.SQLiteDBConn`, accepting the same [libpq keyword arguments](https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-PARAMKEYWORDS) as `psycopg`, or a connection string.

```python
import os
from aisdb.database.dbconn import PostgresDBConn

# keyword arguments
dbconn = PostgresDBConn(
    hostaddr='127.0.0.1',
    port=5432,
    user='postgres',
    dbname='postgres',
    password=os.environ.get('POSTGRES_PASSWORD'),
)

# alternatively, connect using a connection string
dbconn = PostgresDBConn('postgresql://postgres:example@127.0.0.1:5432/postgres')
```

The resulting `dbconn` is used the same way as `SQLiteDBConn` in the [Default Start](../default-start/quick-start.md#querying-the-database) tutorial, passed to `aisdb.DBQuery(dbconn=dbconn, ...)`.

#### Web API

A running `database_server` also exposes AIS tracks over a WebSocket API, returning JSON-formatted vessel vectors in response to queries. This works against any `database_server` instance, including the public MERIDIAN one at `wss://aisviz.cs.dal.ca/ws`, so the example below runs without standing up any local services at all. If you're running your own `database_server` instead (see the [Detailed Start](detailed-start.md)), point `AISDBHOST` at its address. Since requests are utf8-encoded JSON, the same API can be reached from any language capable of speaking the [WebSocket protocol](https://www.rfc-editor.org/rfc/rfc6455), not just Python.

{% code title="websocket_client.py" lineNumbers="true" %}
```python
# Python standard library packages
from datetime import datetime, timedelta
import asyncio
import os
import sys

# These packages need to be installed with pip
import orjson
import websockets.client

# Query the MERIDIAN web API, or reconfigure the URL with an environment variable
db_hostname = 'wss://aisviz.cs.dal.ca/ws'
db_hostname = os.environ.get('AISDBHOST', db_hostname)


class DatabaseRequest():
    ''' Methods in this class generate JSON-formatted AIS requests, as an
        interface to the AISdb WebSocket API. orjson is used for fast
        utf8-encoded JSON serialization.
    '''

    def validrange() -> bytes:
        return orjson.dumps({'msgtype': 'validrange'})

    def zones() -> bytes:
        return orjson.dumps({'msgtype': 'zones'})

    def track_vectors(x0: float, y0: float, x1: float, y1: float,
                       start: datetime, end: datetime) -> bytes:
        ''' database query for a given time range and bounding box '''
        return orjson.dumps(
            {
                "msgtype": "track_vectors",
                "start": int(start.timestamp()),
                "end": int(end.timestamp()),
                "area": {
                    "x0": x0,
                    "x1": x1,
                    "y0": y0,
                    "y1": y1
                }
            },
            option=orjson.OPT_SERIALIZE_NUMPY)


async def query_valid_daterange(db_socket: websockets.client) -> dict:
    ''' Query the database server for minimum and maximum time range values.
        Values are formatted as unix epoch seconds, the total number of
        seconds since Jan 1 1970, 12am UTC.
    '''

    query = DatabaseRequest.validrange()
    await db_socket.send(query)

    response = orjson.loads(await db_socket.recv())
    print(f'Received daterange response from server: {response}')

    start = datetime.fromtimestamp(response['start'])
    end = datetime.fromtimestamp(response['end'])

    return {'start': start, 'end': end}


async def query_tracks_24h(db_socket: websockets.client):
    ''' query recent ship movements near Dalhousie '''

    boundary = {'x0': -64.8131, 'x1': -62.2928, 'y0': 43.5686, 'y1': 45.3673}
    query = DatabaseRequest.track_vectors(
        start=datetime.now() - timedelta(hours=24),
        end=datetime.now(),
        **boundary,
    )
    await db_socket.send(query)

    response = orjson.loads(await db_socket.recv())
    while response['msgtype'] == 'track_vector':
        print(f'got track vector data:\n\t{response}')
        response = orjson.loads(await db_socket.recv())
    print(response, end='\n\n\n')


async def query_zones(db_socket: websockets.client):
    await db_socket.send(DatabaseRequest.zones())

    response = orjson.loads(await db_socket.recv())
    while response['msgtype'] == 'zone':
        print(f'got zone polygon data:\n\t{response}')
        response = orjson.loads(await db_socket.recv())
    print(response, end='\n\n\n')


async def main():
    ''' asynchronously query the web API for valid timerange, 24 hours of
        vectorized vessel data, and zone polygons
    '''
    useragent = 'AISdb WebSocket Client'
    useragent += f' ({os.name} {sys.implementation.cache_tag})'

    async with websockets.client.connect(
            db_hostname, user_agent_header=useragent) as db_socket:
        daterange = await query_valid_daterange(db_socket)
        print(
            f'start={daterange["start"].isoformat()}\t'
            f'end={daterange["end"].isoformat()}',
            end='\n\n\n')

        await query_tracks_24h(db_socket)

        await query_zones(db_socket)


if __name__ == '__main__':
    asyncio.run(main())
```
{% endcode %}

Running the script against the MERIDIAN feed prints the daterange reply first, then one line per track vector as `query_tracks_24h` drains the socket:

```
Received daterange response from server: {'msgtype': 'validrange', 'start': 1690000000.0, 'end': 1751500000.0}
start=2023-07-22T04:26:40  end=2025-07-02T21:26:40

got track vector data:
	{'msgtype': 'track_vector', 'meta': {'mmsi': '316001194'}, 't': [1751496000, 1751496060], 'x': [-63.5734, -63.5701], 'y': [44.6488, 44.6502]}
```

The exact vessels, MMSIs, and timestamps depend on whatever traffic MERIDIAN has ingested at query time, so a re-run will return a different set of tracks.

### Interacting with the Map

The map front end lives in `aisdb_web`, a Vite application that renders vessel tracks over a tile basemap, with a Rust/WebAssembly module (built via `wasm-pack`) handling the heavier geometry work in the browser. It reads the same `VITE_*` variables listed above and is built with `aisdb_web/build_website.sh`, or served locally in development mode with `npm run dev` from that directory once the WebAssembly module is compiled.

You don't need the front end running to see AIS data on a map. The Python package renders the same kind of visualization directly from a query, via `aisdb.web_interface.visualize()`, as shown in the [Default Start](../default-start/quick-start.md#visualization) tutorial. That's the quickest way to check that a query returns the tracks you expect before wiring up a full deployment.
