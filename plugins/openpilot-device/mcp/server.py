# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.2.0", "httpx>=0.27"]
# ///
"""openpilot-device — read-only MCP access to a comma device via the comma connect API.

Two transports, one credential:

  * REST      https://api.commadotai.com   — routes, segments, signed file URLs, stats
  * Athena    https://athena.comma.ai      — JSON-RPC to the device (live cereal messages)

Both authenticate with the same JWT from https://jwt.comma.ai/ (90-day expiry).
Set it in the environment as COMMA_JWT. It is never logged or returned by any tool.

SAFETY — this server is read-only by construction:

  * Every tool builds its own URL path. There is no generic request tool, so the
    model cannot reach an endpoint that is not implemented here.
  * _guard_path() is a second line of defence: it refuses any path touching
    billing, pairing, user management, or navigation, even if a future edit
    introduces one by accident. Cancelling a prime subscription or pushing a
    destination to a moving car must not be one hallucinated argument away.
  * Athena itself exposes no shell, no reboot, and no parameter writes, so the
    live-device surface is inherently observational.
"""

from __future__ import annotations

import os
import time
from collections import deque
from typing import Any

import httpx

# The SDK renamed its high-level server class in 2.0: FastMCP became MCPServer.
# Both expose the same .tool() decorator and .run(), so support either.
try:                                                    # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:                                     # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

API_HOST = os.environ.get("COMMA_API_HOST", "https://api.commadotai.com")
ATHENA_HOST = os.environ.get("COMMA_ATHENA_HOST", "https://athena.comma.ai")

# comma rate-limits the route files endpoint to 5 requests per minute.
FILES_RATE_LIMIT = 5
FILES_RATE_WINDOW = 60.0

# Path fragments this server must never request. See the SAFETY note above.
FORBIDDEN = ("/prime", "pilotpair", "unpair", "add_user", "del_user", "/navigation", "payment")

HTTP_TIMEOUT = 30.0

# The API has no is_online field. Reachability is derived from last_athena_ping,
# a unix timestamp in seconds. Athena's own websocket ping cadence is well under
# a minute, so a few minutes of silence means the device is asleep or off network.
ONLINE_THRESHOLD_S = 300

# Route and device records carry the drive's start/end coordinates and the car's VIN.
# Those identify where the owner lives and works, so they are stripped unless the
# caller explicitly asks for them.
SENSITIVE_FIELDS = (
    "start_lat", "start_lng", "end_lat", "end_lng",
    "last_gps_lat", "last_gps_lng", "last_gps_bearing", "last_gps_speed",
    "vin",
)

mcp = _Server("openpilot-device")

_files_calls: deque[float] = deque()


class DeviceError(RuntimeError):
    """Raised for any condition the caller should see verbatim."""


def _token() -> str:
    token = os.environ.get("COMMA_JWT", "").strip()
    if not token:
        raise DeviceError(
            "COMMA_JWT is not set. Generate a token at https://jwt.comma.ai/ (valid 90 days) "
            "and set it in the environment. Do not paste it into a chat message."
        )
    return token


def _guard_path(path: str) -> None:
    lowered = path.lower()
    for fragment in FORBIDDEN:
        if fragment in lowered:
            raise DeviceError(
                f"Refusing to request {path!r}: this server is read-only and never touches "
                f"billing, pairing, user management, or navigation."
            )


def _explain_status(exc: httpx.HTTPStatusError) -> str:
    code = exc.response.status_code
    if code == 401:
        return ("401 Unauthorized — the JWT is invalid or expired. Tokens last 90 days; "
                "generate a new one at https://jwt.comma.ai/.")
    if code == 403:
        return "403 Forbidden — the token is valid but this account cannot read that device or route."
    if code == 404:
        return ("404 Not Found — check the dongle id or route name. Routes look like "
                "'dongleid|0000004a--a1b2c3d4e5' on current openpilot, or "
                "'dongleid|YYYY-MM-DD--HH-MM-SS' on older versions.")
    if code == 429:
        return "429 Rate limited — the files endpoint allows 5 requests/minute. Wait and retry."
    return f"{code} {exc.response.reason_phrase} — {exc.response.text[:200]}"


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    """GET against the comma REST API. Allowlisted paths only."""
    _guard_path(path)
    url = f"{API_HOST}/{path.lstrip('/')}"
    headers = {"Authorization": f"JWT {_token()}", "User-Agent": "openpilot-claude-kit"}
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        raise DeviceError(_explain_status(exc)) from exc
    except httpx.RequestError as exc:
        raise DeviceError(f"Could not reach {API_HOST}: {exc}") from exc


def _throttle_files() -> None:
    """Enforce the documented 5-per-minute limit on the route files endpoint locally,
    so we surface a clear message instead of provoking a 429."""
    now = time.monotonic()
    while _files_calls and now - _files_calls[0] > FILES_RATE_WINDOW:
        _files_calls.popleft()
    if len(_files_calls) >= FILES_RATE_LIMIT:
        wait = FILES_RATE_WINDOW - (now - _files_calls[0])
        raise DeviceError(
            f"Local rate limit: the route files endpoint allows {FILES_RATE_LIMIT} requests "
            f"per minute. Retry in {wait:.0f}s, or request several routes in one batch."
        )
    _files_calls.append(now)


def _athena(dongle_id: str, method: str, params: dict[str, Any] | None = None) -> Any:
    """Send a JSON-RPC call to the device through athena.

    Athena exposes no shell, no reboot, and no parameter writes — only observational
    methods plus upload management, which this server does not surface.
    """
    url = f"{ATHENA_HOST}/{dongle_id}"
    headers = {"Authorization": f"JWT {_token()}", "User-Agent": "openpilot-claude-kit"}
    body = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": 0}
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            resp = client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            # Athena returns 404 "Device not registered" when the device is simply
            # not connected. That is the common case, not a bad dongle id.
            raise DeviceError(
                f"Athena cannot reach device {dongle_id}: it is not currently connected "
                "(the API returns 404 'Device not registered' for an offline device). "
                "Run verify_connection to see last_seen_seconds_ago. REST tools still "
                "work against already-uploaded data."
            ) from exc
        raise DeviceError(_explain_status(exc)) from exc
    except httpx.RequestError as exc:
        raise DeviceError(f"Could not reach {ATHENA_HOST}: {exc}") from exc

    if isinstance(payload, dict) and payload.get("error"):
        raise DeviceError(
            f"Athena error for {method!r}: {payload['error']}. "
            "The device must be online and connected for athena calls to succeed."
        )
    if isinstance(payload, dict) and "result" in payload:
        return payload["result"]
    return payload


def _redact(payload: Any, include_sensitive: bool = False) -> Any:
    """Strip location and VIN fields from a record or list of records.

    Returns the payload unchanged when include_sensitive is True, so a caller who
    genuinely needs coordinates can still get them — but never by accident.
    """
    if include_sensitive:
        return payload
    if isinstance(payload, list):
        return [_redact(item) for item in payload]
    if isinstance(payload, dict):
        out = {k: v for k, v in payload.items() if k not in SENSITIVE_FIELDS}
        dropped = [k for k in payload if k in SENSITIVE_FIELDS]
        if dropped:
            out["_redacted"] = "location/VIN fields removed; pass include_sensitive=True to keep them"
        return out
    return payload


def _athena_ping_age(device: dict[str, Any]) -> int | None:
    """Seconds since the device last checked in with athena, or None if never."""
    ping = device.get("last_athena_ping")
    if not isinstance(ping, int) or ping <= 0:
        return None
    return max(0, int(time.time()) - ping)


def _is_online(age_seconds: int | None) -> bool:
    return age_seconds is not None and age_seconds < ONLINE_THRESHOLD_S


# --------------------------------------------------------------------------- tools


@mcp.tool()
def verify_connection() -> dict[str, Any]:
    """Check that the JWT works and report what it can reach. Run this first.

    Confirms the token is valid, lists the devices it grants access to, and reports
    whether each one is currently reachable. Never returns the token itself.
    """
    me = _get("v1/me/")
    devices = _get("v1/me/devices/")
    summary = []
    for dev in devices if isinstance(devices, list) else []:
        age = _athena_ping_age(dev)
        summary.append({
            "dongle_id": dev.get("dongle_id"),
            "alias": dev.get("alias"),
            "device_type": dev.get("device_type"),
            "online": _is_online(age),
            "last_seen_seconds_ago": age,
            "prime": dev.get("prime"),
            "openpilot_version": dev.get("openpilot_version"),
        })
    return {
        "ok": True,
        "user_id": me.get("id") if isinstance(me, dict) else None,
        "device_count": len(summary),
        "devices": summary,
        "api_host": API_HOST,
        "note": "There is no is_online field on the API; online is derived from "
                f"last_athena_ping being under {ONLINE_THRESHOLD_S}s old. When a device "
                "is offline, athena tools (live_message, device_runtime_state, "
                "list_device_files) fail with 'Device not registered'. REST route and "
                "file tools still work against already-uploaded data.",
    }


@mcp.tool()
def list_devices(include_sensitive: bool = False) -> Any:
    """List every comma device this token can read.

    Includes alias, type, openpilot version, prime status, serial, and
    last_athena_ping. There is no is_online field — use verify_connection for a
    derived online flag. Last-known GPS is stripped unless include_sensitive=True.
    """
    return _redact(_get("v1/me/devices/"), include_sensitive)


@mcp.tool()
def device_info(dongle_id: str, include_sensitive: bool = False) -> Any:
    """Get details for one device: type, alias, openpilot version, prime, serial.

    Last-known GPS is stripped unless include_sensitive=True.
    """
    return _redact(_get(f"v1.1/devices/{dongle_id}/"), include_sensitive)


@mcp.tool()
def device_stats(dongle_id: str) -> Any:
    """Get aggregate driving statistics for a device (distance, duration, engaged time)."""
    return _get(f"v1.1/devices/{dongle_id}/stats")


@mcp.tool()
def list_routes(dongle_id: str, days_back: int = 7, include_sensitive: bool = False) -> Any:
    """List routes (whole drives) recorded in the last N days.

    A route is one ignition-to-power-down drive. Its name is in the 'fullname' field,
    shaped 'dongleid|<counter>--<hash>' on current openpilot (older devices use
    'dongleid|YYYY-MM-DD--HH-MM-SS'). Pass 'fullname' through verbatim; do not try
    to construct or parse it.

    Widen days_back if nothing comes back; the device only uploads over WiFi, so a
    recent drive can sit unuploaded for days.

    Route records carry the drive's start and end GPS coordinates and the car's VIN.
    Those are stripped by default because they identify where the owner lives and
    works. Set include_sensitive=True only when the coordinates are the point.
    """
    if days_back < 1:
        raise DeviceError("days_back must be at least 1.")
    now_ms = int(time.time() * 1000)
    rows = _get(f"v1/devices/{dongle_id}/routes",
                params={"from": now_ms - days_back * 86_400_000, "to": now_ms})
    return _redact(rows, include_sensitive)


@mcp.tool()
def list_segments(dongle_id: str, days_back: int = 7, include_sensitive: bool = False) -> Any:
    """List individual ~1-minute segments in the last N days.

    Finer grained than list_routes: a 30-minute drive is about 30 segments. Use this
    when you need per-segment detail; use list_routes to find a drive.

    Note this endpoint takes 'start'/'end' rather than the 'from'/'to' used elsewhere
    in the API — passing from/to returns 400.
    """
    if days_back < 1:
        raise DeviceError("days_back must be at least 1.")
    now_ms = int(time.time() * 1000)
    rows = _get(f"v1/devices/{dongle_id}/routes_segments",
                params={"start": now_ms - days_back * 86_400_000, "end": now_ms})
    return _redact(rows, include_sensitive)


@mcp.tool()
def route_info(route_name: str, include_sensitive: bool = False) -> Any:
    """Get metadata for one route: duration, distance, git branch/commit, platform.

    Pass the 'fullname' field from list_routes verbatim — the format varies by
    openpilot version, so never construct it by hand. GPS coordinates and VIN are stripped unless include_sensitive=True.
    """
    return _redact(_get(f"v1/route/{route_name}/"), include_sensitive)


@mcp.tool()
def route_files(route_name: str) -> Any:
    """Get signed download URLs for a route's logs and video.

    Returns short-lived URLs grouped into: logs (full rlogs), qlogs (decimated),
    cameras / dcameras / ecameras (full video), and qcameras (low-res video).

    Expect empty lists. A route commonly has qlogs and qcameras populated while
    'logs' and 'cameras' are empty — full-rate data is only uploaded when the device
    is configured to and has had the WiFi time to do it. An empty 'logs' list means
    the full rlog is not in the cloud, not that the tool failed. Fall back to qlogs,
    or pull the rlog off the device over SSH.

    Rate limited by comma to 5 requests per minute; this server enforces that locally
    and tells you how long to wait rather than letting you hit a 429.
    """
    _throttle_files()
    return _get(f"v1/route/{route_name}/files")


@mcp.tool()
def device_bootlogs(dongle_id: str) -> Any:
    """Retrieve boot logs for a device. Useful when it failed to come up after a change."""
    return _get(f"v1/devices/{dongle_id}/bootlogs")


@mcp.tool()
def device_crashlogs(dongle_id: str) -> Any:
    """Retrieve crash logs for a device."""
    return _get(f"v1/devices/{dongle_id}/crashlogs")


@mcp.tool()
def live_message(dongle_id: str, service: str, timeout_ms: int = 5000) -> Any:
    """Read one live cereal message from a running device, over athena.

    'service' is any cereal service name, for example 'carState', 'deviceState',
    'controlsState', 'carParams', or 'liveLocationKalman'.

    The device must be online and awake. This is a single snapshot, not a stream —
    for anything rate-sensitive, analyse a downloaded rlog instead.
    """
    return _athena(dongle_id, "getMessage", {"service": service, "timeout": timeout_ms})


@mcp.tool()
def device_runtime_state(dongle_id: str) -> dict[str, Any]:
    """Snapshot a live device: openpilot version, network type, metered state, SIM info.

    Combines several athena calls. Individual failures are reported per field rather
    than failing the whole call, so a partially reachable device still tells you
    something useful.
    """
    out: dict[str, Any] = {"dongle_id": dongle_id}
    for label, method in (
        ("version", "getVersion"),
        ("network_type", "getNetworkType"),
        ("network_metered", "getNetworkMetered"),
        ("sim_info", "getSimInfo"),
        ("not_car", "getNotCar"),
    ):
        try:
            out[label] = _athena(dongle_id, method)
        except DeviceError as exc:
            out[label] = f"unavailable: {exc}"
    return out


@mcp.tool()
def list_device_files(dongle_id: str, prefix: str = "") -> Any:
    """List files in the device's data directory, optionally filtered by prefix.

    Useful for seeing what is on the device but not yet uploaded.
    """
    return _athena(dongle_id, "listDataDirectory", {"prefix": prefix})


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
