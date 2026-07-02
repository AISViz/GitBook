---
description: How to deploy your own Automatic Identification System (AIS) receiver.
icon: satellite-dish
cover: ../.gitbook/assets/IMG_3297.jpg
coverY: 0
layout:
  width: default
  cover:
    visible: true
    size: full
  title:
    visible: true
  description:
    visible: true
  tableOfContents:
    visible: true
  outline:
    visible: true
  pagination:
    visible: true
  metadata:
    visible: true
  tags:
    visible: true
  actions:
    visible: true
---

# 📡 AIS Hardware

In addition to utilizing [AIS data provided by Spire](https://spire.com/maritime/?utm_term=spire%20ais%20data\&utm_campaign=Maritime+-+Search+-+Exact\&utm_source=adwords\&utm_medium=ppc\&hsa_acc=4934961383\&hsa_cam=20888450362\&hsa_grp=155753134974\&hsa_ad=685453945378\&hsa_src=g\&hsa_tgt=kwd-922295538895\&hsa_kw=spire%20ais%20data\&hsa_mt=e\&hsa_net=adwords\&hsa_ver=3\&gad_source=1\&gclid=CjwKCAjw74e1BhBnEiwAbqOAjHJkT1RTcEZGEybUWVkwfv9MYvm6ZO-6JOT7diQdXleleG9dHmal1BoCKzcQAvD_BwE) for the Canadian coasts, you can install AIS receiver hardware to capture AIS data directly. The received data can be processed and stored in databases, which can then be used with AISdb. This approach offers additional data sources and allows you to collect and process your own data (as illustrated in the pipeline below). Doing so lets you customize your data collection efforts to meet specific needs and seamlessly integrate the data with AISdb for enhanced analysis and application. At the same time, you can share the data you collect with others.



<figure><img src="https://lh7-rt.googleusercontent.com/slidesz/AGV_vUc6fT3v7BQAiIdFK5InU7VePIbcbiTnRe8xdhnaEyUeJLVPa3eYSrhZH4haXSSalom--oIA8nhXaJLWlgE2pihRVQPzJkyr-4caNB5AiIH5t-6_vMYvtBnd3FthBkpz5JPuuP5sPCMAI5B8eg9Yg5yVNbqfWDiQpH-AOKTHGR44HXIE-Y3H1Ss=s2048?key=y5AqRm_P3gRqgeTbBf2ndA" alt="" width="563"><figcaption><p>Pipeline for capturing and sharing your own AIS data with a VHF Antenna and AISdb.</p></figcaption></figure>

## Requirements

* <mark style="background-color:yellow;">Raspberry Pi or other computers</mark> with internet connectivity

<div align="center" data-full-width="true"><figure><img src="../.gitbook/assets/image (27).png" alt="" width="300"><figcaption><p>Raspberry Pi (Image source: <a href="https://www.raspberrypi.com/products/raspberry-pi-3-model-b/">https://www.raspberrypi.com/products/raspberry-pi-3-model-b/</a>)</p></figcaption></figure></div>

* <mark style="background-color:yellow;">162MHz receiver</mark>, such as the [Wegmatt dAISy 2 Channel Receiver](https://shop.wegmatt.com/collections/frontpage/products/daisy-2-dual-channel-ais-receiver-with-nmea-0183?variant=7103563628580)
* <mark style="background-color:yellow;">An antenna in the VHF frequency band (30MHz - 300MHz)</mark>, _e.g._, Shakespeare QC-4 VHF Antenna
* Optionally, you may want
  * Antenna mount
  * A filtered preamp, such as [this one sold by Uputronics](https://store.uputronics.com/index.php?route=product/product\&path=59\&product_id=93), to improve signal range and quality

Another option is <mark style="background-color:yellow;">**free AIS receivers**</mark> <mark style="background-color:yellow;">from</mark> [<mark style="background-color:yellow;">MarineTraffic</mark>](https://www.marinetraffic.com/en/p/apply-for-free-ais-receiver)<mark style="background-color:yellow;">.</mark> This option may require you to share the data with the organization to help expand its AIS-receiving network.

## Hardware Setup

* When setting up your antenna, place it as high as possible and as far away from obstructions and other equipment as is practical.
* Connect the antenna to the receiver. If using a preamp filter, connect it between the antenna and the receiver.
* Connect the receiver to your Linux device via a USB cable. If using a preamp filter, power it with a USB cable.
*   Validate the hardware configuration

    * When connected via USB, the AIS receiver is typically found under `/dev/` with a name beginning with `ttyACM`, for example `/dev/ttyACM0`. Ensure the device is listed in this directory.
    * To test the receiver, use the command `sudo cat /dev/ttyACM0` to display its output. If all works as intended, you will see streams of bytes appearing on the screen.

    <pre class="language-bash" data-line-numbers><code class="lang-bash">$ sudo cat /dev/ttyACM0
    !AIVDM,1,1,,A,B4eIh>@0&#x3C;voAFw6HKAi7swf1lH@s,0*61
    !AIVDM,1,1,,A,14eH4HwvP0sLsMFISQQ@09Vr2&#x3C;0f,0*7B
    !AIVDM,1,1,,A,14eGGT0301sM630IS2hUUavt2HAI,0*4A
    !AIVDM,1,1,,B,14eGdb0001sM5sjIS3C5:qpt0L0G,0*0C
    !AIVDM,1,1,,A,14eI3ihP14sM1PHIS0a&#x3C;d?vt2L0R,0*4D
    !AIVDM,1,1,,B,14eI@F@000sLtgjISe&#x3C;W9S4p0D0f,0*24
    !AIVDM,1,1,,B,B4eHt=@0:voCah6HRP1;?wg5oP06,0*7B
    !AIVDM,1,1,,A,B4eHWD009>oAeDVHIfm87wh7kP06,0*20
    </code></pre>

Below is the antenna hardware setup MERIDIAN uses.

<figure><img src="../.gitbook/assets/image (21).png" alt="" width="563"><figcaption><p>MERIDIAN AIS hardware setup working at Sandy Cove in Halifax, NS - Canada.</p></figcaption></figure>

## Software Setup

AISdb's receiver is a Rust component exposed to Python as `aisdb.start_receiver()`. It listens for AIS traffic on a UDP or TCP socket, parses the NMEA sentences, and writes the decoded positions and static reports straight into an SQLite or PostgreSQL database. It does not read a serial port directly, so a USB receiver such as the dAISy needs a small bridge program in front of it to forward the serial bytes onto a local network port. `mproxy-client`, the same crate the AISdb receiver links against internally, does that job.

### Install AISdb

On the Raspberry Pi (or whatever Linux box the receiver is plugged into), install Python 3.8 or newer and pull AISdb from PyPI.

{% code lineNumbers="true" %}
```bash
pip install aisdb
```
{% endcode %}

`pip install aisdb` ships prebuilt wheels for the common platforms, so a Rust toolchain is not required just to run the receiver. You only need Rust if you are building AISdb from source.

### Bridge the serial port to a network socket

{% stepper %}
{% step %}
#### Connect the receiver

Attach the dAISy (or equivalent) to the Pi over USB, log in, and update the system with `sudo apt-get update`.
{% endstep %}

{% step %}
#### Install the Rust toolchain

Needed to build `mproxy-client`. Run `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`, then log out and back in so `cargo` is on the path.
{% endstep %}

{% step %}
#### Install `mproxy-client`

Install it from [crates.io](https://crates.io/crates/mproxy-client) by running `cargo install mproxy-client`.
{% endstep %}

{% step %}
#### Create a systemd service

Keeps the bridge running and restarts it if the receiver is unplugged and replugged. Create `./mproxy_client.service`, replacing `User=ais` and `/home/ais` with the username and home directory on your Pi.

{% code title="mproxy_client.service" overflow="wrap" lineNumbers="true" %}
```
[Unit]
Description="AISdb serial-to-UDP bridge"
After=network-online.target

[Service]
Type=simple
User=ais
ExecStart=/home/ais/.cargo/bin/mproxy-client --path /dev/ttyACM0 --server-addr '127.0.0.1:9921'
Restart=always
RestartSec=30

[Install]
WantedBy=default.target
```
{% endcode %}

This forwards whatever the dAISy writes to `/dev/ttyACM0` onto UDP port 9921 on the same machine, where the AISdb receiver will be listening. Run `mproxy-client --help` for the full set of forwarding options if you want to relay to a different host instead.
{% endstep %}

{% step %}
#### Link and enable the service

Starts the bridge at boot.

{% code lineNumbers="true" %}
```bash
sudo systemctl enable systemd-networkd-wait-online.service
sudo systemctl link ./mproxy_client.service
sudo systemctl daemon-reload
sudo systemctl enable mproxy_client
sudo systemctl start mproxy_client
```
{% endcode %}
{% endstep %}
{% endstepper %}

### Run the AISdb receiver

With the bridge forwarding raw NMEA onto `127.0.0.1:9921`, point `aisdb.start_receiver()` at that port. Save this as `./run_receiver.py`.

{% code title="./run_receiver.py" lineNumbers="true" %}
```python
import aisdb

aisdb.start_receiver(
    udp_listen_addr="127.0.0.1:9921",
    sqlite_dbpath="/home/ais/ais_rx.db",
    connect_addr=None,
)
```
{% endcode %}

`sqlite_dbpath` can be swapped for `postgres_connection_string` if you would rather write straight into PostgreSQL. `connect_addr` defaults to `aisviz.cs.dal.ca:9920`, MERIDIAN's public aggregator. Leaving it at the default also merges MERIDIAN's live feed into your own stream, which is convenient if you want a fuller picture of traffic than your antenna alone can see, but set it to `None` (as above) if you only want the messages your own receiver decodes.

Wrap the script in its own systemd service the same way as the bridge, pointing `ExecStart` at your Python interpreter and `run_receiver.py`, and enable it so both services come up together on boot.

## 💡 Common Issues

For some Raspberry Pi hardware (the Raspberry Pi 4 Model B is a common example), the device file Linux assigns to the receiver is not always `/dev/ttyACM0` as used in the systemd unit above.

Check which device file is actually in use.

```bash
ls -l /dev
```

On some boards `serial0` is linked to `ttyS0` rather than a `ttyACM*` device.

Simply changing `/dev/ttyACM0` to `/dev/ttyS0` in the service file may produce garbled AIS sentences, because the default baud rate on that port does not match what the receiver expects. Set the baud rate explicitly.

```bash
stty -F /dev/ttyS0 38400 cs8 -cstopb -parenb
```
