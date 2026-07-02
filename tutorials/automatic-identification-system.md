---
icon: tower-broadcast
description: >-
  An overview of the Automatic Identification System (AIS), the ITU-R M.1371
  message set, transponder classes, MMSI structure, and the limitations of
  AIS as a maritime surveillance data source.
---

# Automatic Identification System

The Automatic Identification System (AIS) is a standardized, unencrypted self-reporting maritime surveillance system. It was developed for collision avoidance and vessel traffic management, and it has become the backbone of modern maritime domain awareness because the same broadcasts that keep ships apart at sea are also picked up by shore stations and satellites and archived for research, safety, and enforcement.

### How does this work?

Every AIS-equipped vessel carries a transponder that broadcasts its identity, position, and movement over VHF radio on two dedicated marine channels (AIS 1 at 161.975 MHz and AIS 2 at 162.025 MHz). Transponders share these channels using a self-organizing time division multiple access scheme, so each unit knows in advance which time slot it may transmit in and does not need a central coordinator.

Reporting rate depends on the vessel's navigational status and speed. An anchored or moored vessel transmits roughly once every three minutes, while a vessel underway and maneuvering can transmit every two seconds. This adaptive rate keeps the channel usable in busy waters while still giving high-speed or maneuvering traffic a near real-time track.

Because AIS is broadcast in the clear, any station within VHF range can receive it. Coastal base stations relay local traffic to shore-based networks, and a growing constellation of AIS-equipped satellites captures transmissions far offshore, well beyond the roughly 40 nautical mile horizon of terrestrial VHF reception.

<figure><img src="../.gitbook/assets/image (4).png" alt="" width="311"><figcaption><p>Image from <a href="https://www.marinelink.com/news/definitive-guide-ais418266">Marinelink</a></p></figcaption></figure>

### The ITU-R M.1371 message set

AIS is standardized under ITU-R Recommendation M.1371, which defines 27 message types, numbered 1 through 27, each carrying a different kind of information in a fixed binary layout. Not every station uses every type. In practice, a handful of message types account for almost all the traffic you will see in a raw AIS feed.

* **Types 1, 2, and 3, Position Report Class A.** The core dynamic report from a Class A transponder. Carries latitude, longitude, speed over ground (SOG), course over ground (COG), true heading, rate of turn (ROT), and navigational status (underway, at anchor, moored, and so on).
* **Type 4, Base Station Report.** Sent by shore stations to broadcast their position and UTC time, which vessels use to keep their onboard clocks synchronized.
* **Type 5, Static and Voyage Related Data.** The Class A "identity card" message. Carries the MMSI, IMO number, call sign, vessel name, ship type, dimensions, destination, and estimated time of arrival.
* **Type 9, Standard SAR Aircraft Position Report.** Used by search-and-rescue aircraft rather than surface vessels.
* **Types 18 and 19, Class B Position Report (standard and extended).** The Class B equivalent of types 1 to 3, with a simpler set of fields and a lower reporting rate.
* **Type 21, Aid-to-Navigation Report.** Broadcast by AIS-equipped buoys, lighthouses, and other fixed navigational aids rather than vessels.
* **Type 24, Static Data Report.** The Class B equivalent of type 5, split across two parts (A and B) because Class B messages are shorter than Class A messages.
* **Type 27, Long Range AIS Broadcast Message.** A compressed position report intended for satellite reception, used when a vessel is far from any base station.

The remaining types cover binary and safety-related messaging (types 6, 7, 8, 12, 13, 14), channel and slot management between base stations and transponders (types 15, 16, 17, 20, 22, 23), and other niche functions. AISdb's decoders parse the position and voyage-relevant subset of this message set out of raw NMEA sentences, since those are the messages that carry ship movement and identity data.

### Class A versus Class B transponders

Not every vessel carries the same equipment, and the class of transponder determines both the reporting rate and the level of detail in the static data.

**Class A** transponders are mandatory under the SOLAS convention for vessels of 300 gross tonnage or more on international voyages, cargo vessels of 500 gross tonnage or more on domestic voyages, and all passenger ships regardless of size. They transmit at up to 12.5 watts, report position as often as every two seconds when maneuvering, and carry the full static and voyage data set (type 5), including destination and ETA.

**Class B** transponders are a lower-cost, lower-power option (typically 2 watts) aimed at fishing boats, pleasure craft, and other vessels not required to carry Class A equipment. They report less frequently, generally every 5 to 30 seconds depending on speed, and their static data (type 24) omits fields like destination and ETA. Class B units also use a different channel access method (carrier-sense TDMA rather than the self-organized TDMA that Class A uses), which means Class B position reports can be deprioritized on a congested channel.

This distinction matters for anyone analyzing AIS data. A dataset built only from Class A traffic will systematically under-represent small craft, and reporting-interval gaps that look like anomalies in a Class B track may simply be normal behavior for that equipment class.

### MMSI structure

The Maritime Mobile Service Identity (MMSI) is the nine-digit number that uniquely identifies a station on the AIS network, and its digit pattern encodes what kind of station it is.

* **Ships** use a plain nine-digit MMSI, where the first three digits are the Maritime Identification Digits (MID), a code assigned by the ITU to the vessel's flag state. For example, MMSIs beginning with 366 through 369 are registered to the United States, and 235 or 232 to the United Kingdom.
* **Coastal stations** use the format `00MIDXXXXX`, with two leading zeros followed by the MID.
* **Group calls to a coastal station** use `0MIDXXXXXX`, with a single leading zero.
* **Aids to navigation** (buoys, lighthouses) use `99MIDXXXXX`, with two leading nines.
* **Craft associated with a parent vessel**, such as a ship's tender, use `98MIDXXXXX`.
* **SAR aircraft** use `111MIDXXX`.
* **AIS search and rescue transmitters** (AIS-SART, man overboard devices, EPIRBs) use MMSIs beginning with 970 through 974.

Because the MID identifies flag state rather than a specific registry authority, MMSIs are not guaranteed to be globally unique in practice. Duplicate, reassigned, or malformed MMSIs are common enough in real-world data that treating MMSI as a perfectly reliable vessel key is a frequent source of downstream error in AIS analysis.

### Dynamic versus static messages

AIS traffic splits into two broad categories that behave very differently in a database.

**Dynamic messages** convey a vessel's real-time state, and their values change from one transmission to the next. This includes speed over ground (SOG), course over ground (COG), rate of turn (ROT), navigational status, and the vessel's current latitude and longitude. These are the high-frequency messages (types 1, 2, 3, 18, 19, and 27) that build up a vessel's track over time.

**Static messages** carry information that stays fixed for the duration of a voyage or longer, such as the Maritime Mobile Service Identity (MMSI), International Maritime Organization (IMO) number, vessel name, call sign, ship type, dimensions, and destination. These arrive far less often (types 5 and 24) since there is no need to retransmit information that has not changed.

This split shapes how AIS data is typically stored and queried. Dynamic reports accumulate into a large, append-only position history, while static reports are better treated as a slowly changing lookup table keyed on MMSI. Joining the two lets you attach vessel identity and characteristics to a raw stream of positions.

### Limitations of AIS signals

AIS is not a complete or tamper-proof picture of maritime traffic, and any analysis built on it should account for a few structural gaps.

1. **Loss of signal.** A vessel can simply turn off its transponder, a practice sometimes called "going dark," to avoid detection during illegal fishing, sanctions evasion, or other activity it does not want tracked. Equipment failure and battery loss on smaller craft produce the same effect unintentionally.
2. **Reception range.** Terrestrial base stations are limited to VHF line-of-sight range, roughly 40 nautical miles depending on antenna height, so open-ocean traffic depends on satellite AIS receivers, and even those have gaps driven by orbital coverage and message collisions in high-traffic areas.
3. **Message integrity.** Because AIS is unencrypted and unauthenticated, positions and identities can be spoofed or manipulated, which means any pipeline consuming raw AIS should treat wildly implausible speeds, positions, or MMSIs as suspect rather than as ground truth.
4. **Uneven adoption.** Not every vessel on the water carries a transponder, and Class B equipment reports less often than Class A, so smaller and non-commercial vessels are consistently under-represented relative to their actual numbers.

To learn more about AIS, refer to [Marinelink's definitive guide to AIS](https://www.marinelink.com/news/definitive-guide-ais418266) or the ITU-R M.1371 recommendation itself.

## References

1. Brousseau, M. (2022). _A comprehensive analysis and novel methods for on-purpose AIS switch-off detection_ \[Master's thesis, Dalhousie University]. DalSpace. [http://hdl.handle.net/10222/81160](http://hdl.handle.net/10222/81160)
2. Kazim, T. (2016, November 14). _A definitive guide to AIS_. MarineLink. Retrieved May 14, 2025, from [https://www.marinelink.com/news/definitive-guide-ais418266](https://www.marinelink.com/news/definitive-guide-ais418266)
3. International Telecommunication Union. (2014). _Technical characteristics for an automatic identification system using time division multiple access in the VHF maritime mobile frequency band_ (Recommendation ITU-R M.1371-5).
