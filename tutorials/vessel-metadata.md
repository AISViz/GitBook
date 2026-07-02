---
description: >-
  Attach vessel particulars, name, IMO, ship type, flag, and tonnage, to
  decoded tracks from a local metadata database or an official API.
icon: ship
---

# ⬇️ Vessel Metadata

AIS position reports carry an MMSI, but static fields such as vessel name, IMO number, ship type, flag, and tonnage are broadcast far less often and are frequently missing from decoded data. This tutorial covers how AISdb attaches vessel metadata from a local metadata database to query results, and where that metadata can come from today.

{% hint style="warning" %}
Earlier AISdb releases shipped web scrapers for VesselFinder and MarineTraffic. Both sites now block automated access and have moved vessel particulars behind paid subscriptions, so the scraping layer no longer works and has been removed from the package. Metadata lookups against a local database still work exactly as before; to acquire new metadata, use an official API such as the MarineTraffic one shown below.
{% endhint %}

## Metadata storage

AISdb caches vessel metadata in a standalone SQLite database, separate from your AIS track database, so it can be joined back onto tracks from any query. `aisdb.webdata.marinetraffic.VesselInfo` opens (or creates) that database and exposes it through its `.trafficDB` attribute. The table layout is one row per MMSI with name, callsign, flag, gross tonnage, summer deadweight, length and breadth, year built, and home port.

If you have a metadata database built with an earlier AISdb release, it remains fully usable. Databases populated from an external source (for example, an API subscription) work as well, as long as they follow the same `webdata_marinetraffic` table schema.

## Attaching metadata to tracks

To read cached metadata and attach it to tracks generated from `TrackGen`, use `aisdb.webdata.marinetraffic.vessel_info`. It takes the track generator and the raw SQLite connection to the traffic database, and merges each track dictionary with the cached row for its MMSI, or a null-filled record if no metadata was found:

{% code title="attach_metadata.py" lineNumbers="true" %}
```python
import aisdb
from datetime import datetime
from aisdb.webdata.marinetraffic import vessel_info, VesselInfo

dbpath = './test_database.db'
start_time = datetime(2021, 7, 1)
end_time = datetime(2021, 7, 2)

with aisdb.SQLiteDBConn(dbpath=dbpath) as dbconn:
    qry = aisdb.DBQuery(
        dbconn=dbconn,
        callback=aisdb.database.sqlfcn_callbacks.in_timerange_validmmsi,
        start=start_time,
        end=end_time,
    )
    rowgen = qry.gen_qry()
    tracks = aisdb.track_gen.TrackGen(rowgen, decimate=False)

    vinfoDB = VesselInfo('./testdata/traffic_info.db').trafficDB
    with vinfoDB as trafficDB:
        for track in vessel_info(tracks, trafficDB):
            print(track['mmsi'], track['marinetraffic_info'])
```
{% endcode %}

Each track dictionary gains a `marinetraffic_info` key holding the cached row (or the null placeholder if that MMSI was never resolved), and `'marinetraffic_info'` is added to the track's `static` field set so downstream code knows to treat it as vessel-level rather than per-position data.

## Acquiring metadata (official API)

MarineTraffic sells a supported REST API with paid subscription tiers. It is not part of AISdb, but it is the supported way to obtain vessel particulars in bulk now that scraping is off the table. The snippet below is illustrative; the exact service name, response fields, and pricing tier depend on your MarineTraffic subscription, so check MarineTraffic's own API documentation for the endpoint and parameters your account has access to.

{% code title="marinetraffic_api.py" lineNumbers="true" %}
```python
import requests

# Your MarineTraffic API key (from a paid subscription)
api_key = 'your_marine_traffic_api_key'

# MMSI numbers to query
mmsi_list = [228386800, 366773000]

# Illustrative endpoint, confirm the exact path and parameters
# against your MarineTraffic subscription's API documentation
url = f'https://services.marinetraffic.com/api/exportvessels/{api_key}'
params = {
    'shipid': ','.join(str(m) for m in mmsi_list),
    'protocol': 'jsono',
    'msgtype': 'extended',
}

response = requests.get(url, params=params)
response.raise_for_status()

for vessel in response.json():
    print(f"Vessel Name: {vessel.get('NAME')}")
    print(f"MMSI: {vessel.get('MMSI')}")
    print(f"IMO: {vessel.get('IMO')}")
    print(f"Flag: {vessel.get('COUNTRY')}")
```
{% endcode %}

Rows fetched this way can be inserted into the `VesselInfo` database so `vessel_info` picks them up on the next join, giving you the same track-merging workflow with a supported data source behind it.
