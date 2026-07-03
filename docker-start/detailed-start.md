---
icon: server
description: Build and run AISdb's Rust database server, receiver, dispatcher, documentation server, and JavaScript/WebAssembly front end natively, without Docker.
hidden: true
---

# 🖥️ Detailed Start

The [Docker Quick Start](quick-start.md) covers running the published `meridiancfi/aisdb` image, which is the fastest way to get the Python package into a disposable environment. This page walks through AISdb's other services (the Rust database server, the receiver, and the JavaScript/WebAssembly map front end), built and run natively, one at a time, without Docker. There's no published `docker-compose.yml` for wiring them together automatically, so use this page for local development, for debugging a single service in isolation, or for deploying AISdb on a host where Docker isn't available.

The stack has three primary components.

> * Database server (Rust WebSocket API)
> * Database storage (PostgreSQL)
> * Web application interface (JavaScript/WebAssembly front end)

It also has three secondary components.

> * Documentation webserver
> * AIS receiver client
> * AIS livestream proxy dispatcher

Every one of these services lives in its own top-level folder in the [AISdb repository](https://github.com/MAPS-Lab/AISdb). All of the Rust components share the same Cargo workspace and Rust toolchain, so installing Rust once with rustup covers the database server, the receiver, the proxy dispatcher, and the WebAssembly build for the front end.

### Dependencies

The following software is required for each AISdb service.

* Database Storage
  * PostgreSQL database server
  * PostgreSQL client libraries
  * See the [PostgreSQL Install Tutorial](https://www.postgresql.org/docs/current/tutorial-install.html)
* Database Server
  * Rustup, the Rust compiler toolchain. [Install Rust](https://www.rust-lang.org/tools/install)
  * OpenSSL
* Web Application Front End
  * Rustup, the Rust compiler toolchain. [Install Rust](https://www.rust-lang.org/tools/install)
  * Binaryen, the WebAssembly optimizer used by `wasm-opt`. [Binaryen](https://github.com/WebAssembly/binaryen)
  * wasm-pack, the Rust to WebAssembly packaging utility. [Install wasm-pack](https://rustwasm.github.io/wasm-pack/installer/)
  * Clang, the C/C++ compiler. [Clang Download](https://releases.llvm.org/download.html)
  * OpenSSL development toolkit (`libssl-dev` on Ubuntu/Debian)
  * pkg-config. [pkg-config](https://en.wikipedia.org/wiki/Pkg-config)
  * Node.js, the JavaScript runtime. [Node.js download](https://nodejs.org/en)
* Documentation Server
  * Python. [Download Python](https://www.python.org/downloads/)
  * Rustup, the Rust compiler toolchain. [Install Rust](https://www.rust-lang.org/tools/install)
  * Maturin build system, to build the AISdb Python package from source. [Maturin User Guide](https://www.maturin.rs/)
  * Sphinx, to build the documentation site from Python docstrings. [Installing and Running Sphinx](https://www.sphinx-doc.org/en/master/#get-started)
  * Node.js, the JavaScript runtime. [Node.js download](https://nodejs.org/en)
* AIS Receiver Client
  * Rustup, the Rust compiler toolchain. [Install Rust](https://www.rust-lang.org/tools/install)
* AIS Proxy Dispatcher
  * Rustup, the Rust compiler toolchain. [Install Rust](https://www.rust-lang.org/tools/install)

{% stepper %}
{% step %}
### Database Storage

Ensure the PostgreSQL server is running by following the [PostgreSQL Database Server Tutorial](https://www.postgresql.org/docs/current/server-start.html). The other services connect to this server to store and retrieve AIS data. AISdb also works against SQLite with no server to run at all, so if you're only experimenting with the Python package rather than the full web stack, skip straight to `pip install aisdb` and use `aisdb.database.dbconn.SQLiteDBConn` instead.

{% endstep %}
{% step %}
### Database Server

The database server is a Rust binary, `aisdb-db-server`, that accepts WebSocket connections and returns JSON-formatted vessel tracks queried from the PostgreSQL database. Configure its connection to PostgreSQL with the same environment variables `psql` and other libpq clients use.

```bash
PGPASSFILE=$HOME/.pgpass
PGUSER="postgres"
PGHOST="[fc00::9]"
PGPORT="5432"
```

`PGPASSFILE` must point at a valid [`.pgpass`](https://www.postgresql.org/docs/current/libpq-pgpass.html) file so the server can read the database password without it appearing in the environment or process list. `AISDBPORT` (default `9924`) sets the port the server listens on for incoming WebSocket queries, and `AISDBHOSTALLOW` (default `[::]`, all interfaces) restricts which client addresses may connect.

Navigate to the `database_server` folder in the project repository, install it with cargo, and run it.

```bash
cd database_server
cargo install --path .
aisdb-db-server
```

On startup the server connects to PostgreSQL, creates its metadata tables if they don't already exist, and starts listening for client connections. Python code can query it directly with [`aisdb.database.dbconn.PostgresDBConn`](https://github.com/MAPS-Lab/AISdb/blob/master/aisdb/database/dbconn.py), or any WebSocket client can query it over the wire, as shown in the [Docker Quick Start](quick-start.md#web-api).

{% endstep %}
{% step %}
### Web Application Front End

The front end is a [Vite](https://vitejs.dev/)-based map application, written in TypeScript and JavaScript, that renders vessel tracks on an OpenStreetMap or Bing Maps basemap. Geometry-heavy operations run client-side through a WebAssembly module compiled from the `client_webassembly` Rust crate, so build that module before building the JavaScript app.

```bash
cd client_webassembly
wasm-pack build --target web --out-dir ../aisdb_web/map/pkg --release
wasm-opt -O3 -o ../aisdb_web/map/pkg/client_bg.wasm ../aisdb_web/map/pkg/client_bg.wasm
```

Then install the JavaScript dependencies and build the map application from the `aisdb_web` folder. The `VITE_*` environment variables point the built app at the database server from the previous section; see the full list in the [Docker Quick Start environment section](quick-start.md#environment).

```bash
cd aisdb_web
npm install
cd map
VITE_AISDBHOST=localhost VITE_AISDBPORT=9924 VITE_DISABLE_SSL_DB=1 npx vite build --outDir ../dist_map
```

Finally, serve the built files with the bundled Express server.

```bash
node server.js
```

The front end listens on port `8080` by default and serves the contents of `dist_map`, which was just produced by the Vite build.

{% endstep %}
{% step %}
### Documentation Server

The documentation server serves this GitBook-style documentation site alongside the API reference generated from the AISdb Python package's docstrings. Building it requires a working AISdb development install, since Sphinx imports the package to read its docstrings.

```bash
pip install --upgrade maturin[patchelf]
maturin develop --release --extras=docs
```

`maturin develop --extras=docs` compiles the Rust extension and installs AISdb in editable mode along with its `docs` extra (`sphinx` and `sphinx-rtd-theme`). With that in place, build the static site from the `docs` folder.

```bash
cd docs
bash build_docs.sh
```

The script runs `sphinx-apidoc` against the `aisdb` package to regenerate the API reference pages, then builds the full HTML site into `docs/dist_sphinx`. Install the Node.js dependencies and serve the result.

```bash
npm install
node docserver.js
```

The documentation server listens on port `8081` and serves `dist_sphinx` at `/`, plus a `dist_coverage` folder at `/coverage` if a coverage report has been generated separately.

{% endstep %}
{% step %}
### AIS Receiver Client

The receiver client is a Rust binary, `aisdb-receiver`, that decodes incoming NMEA AIS sentences and writes the resulting vessel positions and static data to SQLite or PostgreSQL. Build and install it from the `receiver` folder.

```bash
cd receiver
cargo install --path .
```

`aisdb-receiver` takes its configuration entirely from command line flags rather than environment variables. The most commonly used ones are `--path` for an SQLite database file, `--postgres-connect` for a PostgreSQL connection string, `--udp-listen-addr` for the UDP socket that raw AIS sentences arrive on, and `--tcp-output-addr` together with `--multicast-addr-parsed` to publish parsed, JSON-formatted messages over a WebSocket for downstream consumers such as the web front end. Run `aisdb-receiver --help` for the complete list.

```bash
aisdb-receiver --udp-listen-addr 0.0.0.0:9921 --postgres-connect "postgresql://postgres@localhost:5432" --tcp-output-addr 0.0.0.0:9922 --multicast-addr-parsed 127.0.0.1:9923
```

{% endstep %}
{% step %}
### AIS Proxy Dispatcher

There's no separate binary for the proxy dispatcher. It's the same `aisdb-receiver` binary from the previous section, run a second time with a different combination of flags so it acts as a reverse proxy instead of a decoder. Run this way, `aisdb-receiver` listens for messages already parsed and forwarded by a receiver instance, then republishes them to downstream TCP or UDP clients, which is what lets the web front end subscribe to a live AIS feed without connecting to the database server at all.

```bash
cd receiver
aisdb-receiver --tcp-connect-addr upstream-receiver-host:9922 --tcp-output-addr 0.0.0.0:9922 --udp-output-addr 0.0.0.0:9921
```

`--tcp-connect-addr` pulls the parsed message stream from an upstream receiver, and `--tcp-output-addr`/`--udp-output-addr` republish it to whichever downstream clients or channels need it. Since it's one binary serving two roles, the receiver and the proxy dispatcher can also be combined into a single process by passing both sets of flags at once, which is useful for small deployments that don't need the two roles split across hosts.
{% endstep %}
{% endstepper %}

### Putting It Together

None of these services depend on each other at build time, only at run time, so the order to start them is Database Storage, then Database Server, then (optionally) AIS Receiver Client and AIS Proxy Dispatcher, then the Web Application Front End and Documentation Server. If you only need the Python package rather than the full self-hosted stack, the [Docker Quick Start](quick-start.md) gets you there in two commands with the published image. Reach for this page whenever you need to change, debug, or deploy just one of the native services on its own.
