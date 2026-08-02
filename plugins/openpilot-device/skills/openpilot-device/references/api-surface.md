# comma connect API surface

What the API offers, what this server exposes, and what it deliberately does not.

**Everything below was verified against a live account.** Where comma's published spec
at <https://api.comma.ai/> disagrees with the running API, the running API is recorded
here and the discrepancy is called out.

## Hosts and auth

| Purpose | Host |
|---|---|
| REST API | `https://api.commadotai.com` |
| Athena RPC | `https://athena.comma.ai` |

The REST host is **`api.commadotai.com`**; `api.comma.ai` serves the documentation.

Auth header on every request: `Authorization: JWT <token>`, from
<https://jwt.comma.ai/>, 90-day expiry.

Device records carry an `athena_host` field, but its value is an **internal cluster
hostname** that does not resolve publicly. Ignore it and use `athena.comma.ai`.

## Corrections to the published spec

These cost real debugging time. All four are verified.

| Spec says | Reality |
|---|---|
| `GET /v1/devices/:id/segments` | **404.** Use `/v1/devices/:id/routes` for drives, or `/v1/devices/:id/routes_segments` for segments. |
| `/routes_segments` takes `from`/`to` | **400.** It takes **`start`/`end`**. Other endpoints do use `from`/`to`. |
| `GET /v1/route/:name/segments` | **404.** No such endpoint. Filter `routes_segments` instead. |
| Devices have `is_online` | **No such field.** Derive from `last_athena_ping` (unix seconds). |

Route names also do not match the documented shape. A current device produces
`dongleid|0000004a--a1b2c3d4e5`; older ones produce `dongleid|YYYY-MM-DD--HH-MM-SS`.
Always take `fullname` and pass it through verbatim.

## Exposed by this server

### REST

| Tool | Endpoint | Verified |
|---|---|---|
| `verify_connection` | `GET /v1/me/` + `/v1/me/devices/` | ✅ |
| `list_devices` | `GET /v1/me/devices/` | ✅ |
| `device_info` | `GET /v1.1/devices/:id/` | ✅ |
| `device_stats` | `GET /v1.1/devices/:id/stats` → `{all, week}` | ✅ |
| `list_routes` | `GET /v1/devices/:id/routes?from=&to=` | ✅ |
| `list_segments` | `GET /v1/devices/:id/routes_segments?start=&end=` | ✅ |
| `route_info` | `GET /v1/route/:name/` | ✅ |
| `route_files` | `GET /v1/route/:name/files` — **5/min** | ✅ |
| `device_bootlogs` | `GET /v1/devices/:id/bootlogs` → `list[str]` | ✅ |
| `device_crashlogs` | `GET /v1/devices/:id/crashlogs` → `list[str]` | ✅ |

`route_files` returns six keys: `logs`, `qlogs`, `cameras`, `dcameras`, `ecameras`,
`qcameras`. **Empty lists are normal.** On a verified route, `qlogs` and `qcameras` had
11 entries each while `logs` and `cameras` were empty — full-rate data is uploaded only
when the device is configured for it. Signed URLs point at
`commadata2.blob.core.windows.net`.

### Athena JSON-RPC

`POST https://athena.comma.ai/:dongle_id`, JSON-RPC 2.0.

| Tool | Method | Verified |
|---|---|---|
| `live_message` | `getMessage(service, timeout)` | ✅ |
| `device_runtime_state` | `getVersion`, `getNetworkType`, `getNetworkMetered`, `getSimInfo`, `getNotCar` | ✅ |
| `list_device_files` | `listDataDirectory(prefix)` | ✅ |

The documented envelope works, and the server is stricter than it needs to be: a live
device answered with `jsonrpc` omitted, with `params` omitted, and with an extra
`expiry` key. The response `id` is a server-generated UUID, not the id you sent — do not
match on it.

Verified payload sizes: `deviceState` 34 fields, `carState` 50, `controlsState` 11.
`listDataDirectory` returned 2266 entries on a device with a month of drives.

### Athena failure modes

| Status | Means |
|---|---|
| 404 `Device not registered` | Device known, no live connection right now |
| 401 `Unauthorized` | Token cannot reach that dongle id |

**A fresh `last_athena_ping` does not guarantee 404 will not happen.** The websocket is
established shortly after the ping, so there is a window where the device looks online
and athena still refuses. Observed: a device reporting `last_seen=70s` returned 404, then
succeeded about a minute later. Retry rather than concluding the device is broken.

Only `athena.comma.ai/:dongle_id` works. `athena.comma.ai/v1/:dongle_id`,
`api/v1/devices/:id/athena`, `api/v1/athena/:id`, and `api/v1/devices/:id/rpc` all 404.
`GET /v1/devices/:id/athena_offline_queue` works and returns `[]` on a live device.

## Privacy: fields stripped by default

Route, segment, and device records carry data that identifies the owner:

`start_lat`, `start_lng`, `end_lat`, `end_lng`, `last_gps_lat`, `last_gps_lng`,
`last_gps_bearing`, `last_gps_speed`, `vin`

Every route row includes the start and end coordinates of that drive — in practice, the
owner's home and workplace — and the car's VIN. A 20-route listing therefore maps
someone's month of movements.

The server strips these unless a tool is called with `include_sensitive=True`, and marks
the record with `_redacted` so the omission is visible. Non-sensitive identifiers
(`dongle_id`, `user_id`) are left in place; they are needed to make further calls.

## Never exposed, by design

`_guard_path()` refuses any path containing these fragments, even if a tool is added by
mistake.

| Endpoint | Why |
|---|---|
| `POST /v1/prime/cancel` | Cancels the subscription |
| `POST /v1/prime/pay`, `/payment_source` | Billing |
| `POST /v2/pilotpair/`, `/v1/devices/:id/unpair` | Pairing state |
| `POST /v1/devices/:id/add_user`, `/del_user` | Grants or revokes device access |
| `PATCH /v1/devices/:id/` | Renames the device |
| `POST /v1/navigation/:id/set_destination` | **Pushes a destination to a moving car** |
| `/v1/navigation/:id/locations` (PUT/PATCH/DELETE) | Mutates saved locations |

Navigation and billing are the ones that matter. A generic API-proxy tool would put
"cancel your subscription" and "redirect the car" one hallucinated argument away.
Allowlisting specific endpoints is the whole safety model.

## Available but not exposed

- **Derived route data** via signed-URL suffixes: `/route.coords` (GPS path),
  `/events.json`, `/sec{N}.jpg` frames. Unverified.
- **HLS video**: `/hls/:dongle_id/:route_sig/index.m3u8` and the `dcamera` variant. A
  stream URL is of little use without a player.
- **Athena methods left out**: `uploadFileToUrl`, `uploadFilesToUrls`, `listUploadQueue`,
  `cancelUpload`, `setRouteViewed`, `startStream`, `startLocalProxy`, `echo`,
  `getPublicKey`, `getSshAuthorizedKeys`, `getGithubUsername`. The upload family mutates
  device state and spends the owner's bandwidth; the key and username getters return
  account-identifying data with no diagnostic value.

## SDK note

The `mcp` Python SDK renamed its high-level server class in 2.0: `FastMCP` became
`MCPServer` at `mcp.server.mcpserver`. Both expose the same `.tool()` decorator and
`.run()`. `server.py` imports whichever is present, so it runs on 1.x and 2.x.
