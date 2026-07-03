---
description: Build the AISdb Rust core and Python interface from source.
hidden: true
icon: gears
cover: >-
  https://images.unsplash.com/photo-1515879218367-8466d910aaa4?crop=entropy&cs=srgb&fm=jpg&ixid=M3wxOTcwMjR8MHwxfHNlYXJjaHw4fHxwcm9ncmFtbWluZ3xlbnwwfHx8fDE3MjMzMDE5OTV8MA&ixlib=rb-4.0.3&q=85
coverY: 0
---

# ⚙️ Compile AISdb

### Why build from source

Most users should just install a pre-compiled wheel with `pip install aisdb`, as described in the [Quick Start](quick-start.md) guide. Build from source instead if you want to contribute to AISdb, need a change that hasn't shipped to PyPI yet, or are working on a platform without a pre-built wheel.

AISdb's performance-critical code (message decoding, the R\* tree indexing, and the live receiver) is written in Rust and exposed to Python through [PyO3](https://pyo3.rs/), with [Maturin](https://www.maturin.rs/) driving the build. `pip install aisdb` simply pulls a wheel that was already produced by this same pipeline. Building from source means running that pipeline yourself.

### Prerequisites

<table><thead><tr><th width="220">Tool</th><th>Why you need it</th></tr></thead><tbody><tr><td>Python 3.8 or newer</td><td>AISdb's <code>pyproject.toml</code> declares <code>requires-python = "&#x3E;=3.8"</code>.</td></tr><tr><td>Git</td><td>To clone the repository.</td></tr><tr><td>Rust (stable, via <a href="https://rustup.rs/">rustup</a>)</td><td>Compiles the <code>aisdb</code> crate and its <code>aisdb-lib</code>/<code>aisdb-receiver</code> workspace members. No nightly toolchain is required.</td></tr><tr><td>Maturin &#x3E;=1.0</td><td>The build backend declared in <code>pyproject.toml</code> (<code>build-backend = "maturin"</code>). It compiles the Rust extension and installs it into your active Python environment.</td></tr><tr><td>Node.js/npm and <a href="https://rustwasm.github.io/wasm-pack/installer/">wasm-pack</a></td><td>AISdb's build script bundles the browser-based visualization frontend (<code>aisdb_web/</code>) as part of every build, compiling a WebAssembly module and running a Vite build. Without <code>wasm-pack</code> and <code>npm</code> on your <code>PATH</code>, the Rust build fails.</td></tr><tr><td><code>patchelf</code> (Linux only)</td><td>Used by Maturin to fix up shared library paths for a manylinux-compatible wheel.</td></tr></tbody></table>

With those in place, the build itself follows the same three-step pattern on every platform. Activate a virtual environment, clone the repository, then run `maturin develop --release`.

{% tabs %}
{% tab title="Linux" icon="linux" %}
{% code title="build-linux.sh" lineNumbers="true" %}
```bash
# Install the Rust toolchain
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"

# Create and activate a virtual environment
python -m venv AISdb
source ./AISdb/bin/activate

# Install Maturin and patchelf
pip install --upgrade "maturin[patchelf]"

# Install wasm-pack, required to bundle the visualization frontend
curl https://rustwasm.github.io/wasm-pack/installer/init.sh -sSf | sh

# Clone the source code and move into the package root
git clone https://github.com/MAPS-Lab/AISdb.git && cd aisdb

# Build and install AISdb into your virtual environment
maturin develop --release --extras=test,docs
```
{% endcode %}

The `--extras=test,docs` flag pulls in the optional dependency groups declared in `pyproject.toml` (`pytest`/`coverage` for the test suite, `sphinx` for the documentation build). Drop it if you only want the runtime package.
{% endtab %}

{% tab title="macOS" icon="apple" %}
The flow is identical to Linux. Make sure the Xcode Command Line Tools are installed first, since Rust needs a system linker and C compiler to build native extensions.

{% code title="build-macos.sh" lineNumbers="true" %}
```bash
# Xcode Command Line Tools (skip if already installed)
xcode-select --install

# Install the Rust toolchain
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"

# Create and activate a virtual environment
python -m venv AISdb
source ./AISdb/bin/activate

# Install Maturin
pip install --upgrade maturin

# Install wasm-pack, required to bundle the visualization frontend
curl https://rustwasm.github.io/wasm-pack/installer/init.sh -sSf | sh

# Clone the source code and move into the package root
git clone https://github.com/MAPS-Lab/AISdb.git && cd aisdb

# Build and install AISdb into your virtual environment
maturin develop --release --extras=test,docs
```
{% endcode %}

`patchelf` is a Linux-only tool for repairing ELF shared libraries, so it isn't needed on macOS.
{% endtab %}

{% tab title="Windows" icon="windows" %}
1. Install Python 3.8 or newer from [python.org](https://www.python.org/downloads/) and make sure "Add python.exe to PATH" is checked during setup.
2. Install Rust from [rust-lang.org](https://www.rust-lang.org/tools/install) by running `rustup-init.exe` and accepting the default option, which installs the MSVC toolchain along with the Visual Studio C++ Build Tools that Rust's linker needs on Windows.
3. Install [Node.js](https://nodejs.org/) (npm ships with it) and [wasm-pack](https://rustwasm.github.io/wasm-pack/installer/), both required to bundle the visualization frontend during the build.
4. Open a terminal (PowerShell or `cmd`) and follow the same clone-and-build steps as Linux and macOS.

{% code title="build-windows.ps1" lineNumbers="true" %}
```powershell
# Create and activate a virtual environment
python -m venv AISdb
.\AISdb\Scripts\activate

# Install Maturin
pip install --upgrade maturin

# Clone the source code and move into the package root
git clone https://github.com/MAPS-Lab/AISdb.git
cd aisdb

# Build and install AISdb into your virtual environment
maturin develop --release --extras=test,docs
```
{% endcode %}

If the build fails to link OpenSSL, install it through [vcpkg](https://github.com/microsoft/vcpkg) and make sure `VCPKG_ROOT` is on your `PATH`. That's the mechanism the `openssl-sys` crate uses to find OpenSSL on Windows.
{% endtab %}
{% endtabs %}

### Troubleshooting the 1.8.0-alpha tag on a recent Rust toolchain

The lockfiles shipped with the 1.8.0-alpha tag pin `wasm-bindgen` to a version that no longer compiles on current stable Rust. If your build stops with

```
error: older versions of the `wasm-bindgen` crate are incompatible with
current versions of Rust; please update to `wasm-bindgen` v0.2.88
```

update the pin in both lockfiles before rebuilding. The repository root and `client_webassembly/` each carry their own `Cargo.lock`, and the WebAssembly build is the one that usually trips.

{% code lineNumbers="true" %}
```bash
cargo update -p wasm-bindgen                      # root lockfile
cd client_webassembly && cargo update -p wasm-bindgen && cd ..
```
{% endcode %}

If the follow-up build then fails inside `wasm-bindgen-macro-support` with a `syn`-related trait error, bump that crate in `client_webassembly/` as well with `cargo update -p syn`. Avoid a blanket `cargo update` there, since newer `geojson` releases changed their API and no longer match the pinned code. Builds from the `master` branch are not affected.

### Verifying the build

Once `maturin develop --release` finishes, the compiled extension is installed directly into your active virtual environment, no separate `pip install` step needed. Confirm it worked with the following command.

{% code lineNumbers="true" %}
```bash
python -c "import aisdb; print(aisdb.__version__)"
```
{% endcode %}

This should print `1.8.0-alpha` (or whatever version is checked out from `Cargo.toml`/`pyproject.toml`).

If you installed the `test` extra, you can also run the test suite from the repository root to confirm everything is wired up correctly.

{% code lineNumbers="true" %}
```bash
pytest
```
{% endcode %}

### Rebuilding after changes

`maturin develop --release` only needs to be re-run when the Rust source under `src/`, `aisdb_lib/`, or `receiver/` changes. Editing the pure-Python code under `aisdb/` takes effect immediately since it's installed in place, no rebuild required. If you're iterating on Rust code frequently, drop `--release` for a much faster debug build while you're testing, then switch back to `--release` before benchmarking or shipping a wheel.
