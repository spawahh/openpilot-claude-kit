---
name: openpilot-device
description: >-
  Inspect a comma device and its recorded drives through the comma connect API —
  list routes, download rlogs via signed URLs, read boot and crash logs, and read
  live cereal messages from an online device. Use when asked to check a drive, look
  at what a device recorded, diagnose on-road behaviour, pull a log, check whether a
  device is online, or investigate a crash. Trigger on "comma", "dongle", "route",
  "rlog", "qlog", "connect.comma.ai", "athena", "my drive", "my device", or a route
  name containing a "|", such as "dongleid|0000004a--a1b2c3d4e5".
---

# Working with a comma device over the connect API

This skill pairs with the `openpilot-device` MCP server, which exposes the comma
connect API as read-only tools. No SSH, no local network access, no Prime proxy
config — one JWT covers both transports.

## Setup

1. Generate a token at <https://jwt.comma.ai/>. It is valid for **90 days**.
2. Put it in the environment as `COMMA_JWT`. Never paste it into a chat message —
   it is a bearer credential for the account, not just the device.
3. Run `verify_connection` first. It confirms the token works and lists reachable
   devices without echoing the token back.

When a tool returns `401`, the token has expired. Regenerate it; nothing else is wrong.

## The two transports, and when each fails

| Transport | Tools | Works when |
|---|---|---|
| REST | routes, files, stats, boot/crash logs | Always — reads data already uploaded to comma's cloud |
| Athena | `live_message`, `device_runtime_state`, `list_device_files` | **Only when the device is online and awake** |

This distinction causes most confusion. A parked device that has uploaded its drives
answers every REST tool and fails every athena tool. That is normal, not a fault.

**There is no `is_online` field on the API.** `verify_connection` derives `online` from
how recently `last_athena_ping` was updated, and reports `last_seen_seconds_ago` so you
can judge for yourself.

**`online: true` does not guarantee athena will answer.** A fresh ping is necessary but
not sufficient — the websocket comes up shortly after the ping, so there is a window
where the device looks online and athena still returns 404. Observed in practice: a
device reporting `last_seen=70s` returned 404, then succeeded a minute later. If you get
404 on a device that looks online, wait and retry rather than concluding it is broken.

Athena's two failures are distinct and the server reports them differently:

| Status | Means |
|---|---|
| 404 `Device not registered` | Device known, no live connection right now. Retry. |
| 401 `Unauthorized` | The token cannot reach that dongle id. Check it against `list_devices`. |

## Finding a drive

A route covers one ignition-to-power-down drive. Segments are about one minute each,
so a 30-minute drive is roughly 30 segments.

```
list_routes(dongle_id, days_back=7)     # whole drives; widen days_back if empty
list_segments(dongle_id, days_back=7)   # ~1-minute granularity
route_info(route_name)
```

**Take the route name from the `fullname` field and pass it through verbatim.** The
format changed between openpilot versions — current devices produce
`dongleid|0000004a--a1b2c3d4e5`, older ones `dongleid|YYYY-MM-DD--HH-MM-SS`. Never
construct or parse it.

**Route records carry the drive's start and end GPS coordinates and the car's VIN.**
The server strips those by default. They identify where the owner lives and works, so
only pass `include_sensitive=True` when the coordinates are genuinely the point, and
do not echo them into a summary afterwards.

**Nothing showing up is usually upload lag, not a missing drive.** Devices upload over
WiFi, so a drive can sit on the device for days if the car never parks near a known
network. Check `list_device_files` (athena, device must be online) to see what exists
locally but has not been uploaded.

## Getting logs

`route_files(route_name)` returns short-lived signed URLs grouped into `logs` (full
rlogs), `qlogs` (decimated), `cameras`/`dcameras`/`ecameras` (full video), and
`qcameras` (low-res video).

**Expect empty lists.** A route commonly has `qlogs` and `qcameras` populated while
`logs` and `cameras` are empty — full-rate data is uploaded only when the device is
configured for it and has had the WiFi time. An empty `logs` list means the rlog is not
in the cloud, not that the call failed. Fall back to qlogs, or pull the rlog off the
device over SSH.

**The files endpoint is rate limited to 5 requests per minute.** The server enforces
this locally and tells you how long to wait. Plan the routes you need up front instead
of looping — burning the budget on exploratory calls means a minute of dead time.

Prefer **qlogs** for a first pass: they are far smaller than rlogs and carry the
decimated versions of most fields. Reach for the full rlog only when you need a signal
at full rate.

## Reading live state

```
live_message(dongle_id, "carState")
live_message(dongle_id, "deviceState")
device_runtime_state(dongle_id)
```

`live_message` is **one snapshot, not a stream**. Do not try to characterise anything
rate-sensitive by calling it repeatedly — the sampling is uncontrolled and the round
trip goes through comma's servers. For anything involving timing, rates, or transient
behaviour, download the rlog and analyse it offline.

## What this cannot do

- **No shell.** Athena exposes no command execution, no reboot, and no parameter
  writes. Building, deploying, or editing anything on the device needs SSH, which is
  outside this plugin.
- **No live CAN sniffing.** `getMessage` cannot substitute for capturing raw CAN at
  rate. Signal-hunting work needs a device-side capture over SSH.
- **No control.** Nothing here can engage, disengage, or actuate anything.

Say so plainly when a request needs one of these, rather than approximating it with
repeated `live_message` calls.

## Safety

This reads from a device that drives a real car. Everything here is observational —
the server never writes, and deliberately cannot reach comma's billing, pairing, or
navigation endpoints. Keep it that way: if a future version adds a mutating tool, it
must refuse to run while the car is onroad.
