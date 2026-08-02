# comma connect API surface

Reference for what the API offers, what this server exposes, and what it deliberately
does not. Sourced from comma's published spec at <https://api.comma.ai/> and from
openpilot's own client code (`tools/lib/api.py`, `system/athena/athenad.py`).

## Hosts and auth

| Purpose | Host |
|---|---|
| REST API | `https://api.commadotai.com` |
| Athena RPC | `https://athena.comma.ai` |
| Video / HLS | `https://video.comma.ai` |

Note the REST host is **`api.commadotai.com`**, not `api.comma.ai` — the latter serves
the documentation. Getting this wrong produces confusing failures.

Auth header on every request: `Authorization: JWT <token>`, token from
<https://jwt.comma.ai/>, 90-day expiry.

openpilot's own client retries `500/502/503/504` with exponential backoff and treats
`401`/`403` as unauthorized. This server mirrors that behaviour in its error messages.

## Exposed by this server

### REST

| Tool | Endpoint |
|---|---|
| `verify_connection` | `GET /v1/me/` + `GET /v1/me/devices/` |
| `list_devices` | `GET /v1/me/devices/` |
| `device_info` | `GET /v1.1/devices/:dongle_id/` |
| `device_stats` | `GET /v1.1/devices/:dongle_id/stats` |
| `list_routes` | `GET /v1/devices/:dongle_id/segments?from=&to=` |
| `route_info` | `GET /v1/route/:route_name/` |
| `route_segments` | `GET /v1/route/:route_name/segments` |
| `route_files` | `GET /v1/route/:route_name/files` — **5/min** |
| `device_bootlogs` | `GET /v1/devices/:dongle_id/bootlogs` |
| `device_crashlogs` | `GET /v1/devices/:dongle_id/crashlogs` |

### Athena JSON-RPC

`POST https://athena.comma.ai/:dongle_id` with a JSON-RPC 2.0 body.

| Tool | Method |
|---|---|
| `live_message` | `getMessage(service, timeout)` |
| `device_runtime_state` | `getVersion`, `getNetworkType`, `getNetworkMetered`, `getSimInfo`, `getNotCar` |
| `list_device_files` | `listDataDirectory(prefix)` |

## Available but not exposed

### Derived route data

Signed URLs from `route_files` support suffixes that avoid decoding anything yourself:

- `/route.coords` — the GPS path
- `/events.json` — route events
- `/sec{N}.jpg` — a frame every 5 seconds

Not wired into tools yet; worth adding once response shapes are confirmed against a
real token.

### HLS video

- `GET /hls/:dongle_id/:route_sig/index.m3u8` — road camera
- `GET /hls/:dongle_id/:route_sig/dcamera/index.m3u8` — driver camera

Not exposed: an MCP tool returning a video stream URL has little value without a player.

### Athena methods left out

`uploadFileToUrl`, `uploadFilesToUrls`, `listUploadQueue`, `cancelUpload`,
`setRouteViewed`, `startStream`, `startLocalProxy`, `echo`, `getPublicKey`,
`getSshAuthorizedKeys`, `getGithubUsername`.

The upload family mutates device state and consumes the owner's bandwidth. The key and
username getters return account-identifying data with no diagnostic value.

## Never exposed, by design

These exist in the API and must stay unreachable. `_guard_path()` in the server refuses
any path containing them even if a tool is added by mistake.

| Endpoint | Why |
|---|---|
| `POST /v1/prime/cancel` | Cancels the subscription |
| `POST /v1/prime/pay`, `/payment_source` | Billing and payment methods |
| `POST /v2/pilotpair/`, `/v1/devices/:id/unpair` | Pairing state |
| `POST /v1/devices/:id/add_user`, `/del_user` | Grants or revokes device access |
| `PATCH /v1/devices/:id/` | Renames the device |
| `POST /v1/navigation/:id/set_destination` | **Pushes a destination to a moving car** |
| `/v1/navigation/:id/locations` (PUT/PATCH/DELETE) | Mutates saved locations |

The navigation and billing entries are the ones that matter. A generic API-proxy tool
would put "cancel your subscription" and "redirect the car" one hallucinated argument
away. Allowlisting specific endpoints is the whole safety model.

## Verification status

Every endpoint above is transcribed from comma's spec and openpilot's source. **None
has been executed** — that requires a live token. Expect response-shape surprises on
first real use, particularly in `verify_connection`, which assumes `/v1/me/devices/`
returns a list of objects carrying `dongle_id`, `alias`, `device_type`, `is_online`,
and `prime`.
