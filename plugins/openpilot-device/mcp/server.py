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
from mcp.server.fastmcp import FastMCP

API_HOST = os.environ.get("COMMA_API_HOST", "https://api.commadotai.com")
ATHENA_HOST = os.environ.get("COMMA_ATHENA_HOST", "https://athena.comma.ai")

# comma rate-limits the route files endpoint to 5 requests per minute.
FILES_RATE_LIMIT = 5
FILES_RATE_WINDOW = 60.0

# Path fragments this server must never request. See the SAFETY note above.
FORBIDDEN = ("/prime", "pilotpair", "unpair", "add_user", "del_user", "/navigation", "payment")

HTTP_TIMEOUT = 30.0

mcp = FastMCP("openpilot-device")

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
                "'dongleid|YYYY-MM-DD--HH-MM-SS'.")
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


# --------------------------------------------------------------------------- tools


@mcp.tool()
def verify_connection() -> dict[str, Any]:
    """Check that the JWT works and report what it can reach. Run this first.

    Confirms the token is valid, lists the devices it grants access to, and reports
    whether each one is currently online. Never returns the token itself.
    """
    me = _get("v1/me/")
    devices = _get("v1/me/devices/")
    summary = []
    for dev in devices if isinstance(devices, list) else []:
        summary.append({
            "dongle_id": dev.get("dongle_id"),
            "alias": dev.get("alias"),
            "device_type": dev.get("device_type"),
            "online": dev.get("is_online"),
            "prime": dev.get("prime"),
        })
    return {
        "ok": True,
        "user_id": me.get("id") if isinstance(me, dict) else None,
        "email": me.get("email") if isinstance(me, dict) else None,
        "device_count": len(summary),
        "devices": summary,
        "api_host": API_HOST,
        "note": "If a device shows online=false, athena live-message tools will fail; "
                "REST route and file tools still work against uploaded data.",
    }


@mcp.tool()
def list_devices() -> Any:
    """List every comma device this token can read, with alias, type, and online state."""
    return _get("v1/me/devices/")


@mcp.tool()
def device_info(dongle_id: str) -> Any:
    """Get device details: type, alias, online state, openpilot version, prime status."""
    return _get(f"v1.1/devices/{dongle_id}/")


@mcp.tool()
def device_stats(dongle_id: str) -> Any:
    """Get aggregate driving statistics for a device (distance, duration, engaged time)."""
    return _get(f"v1.1/devices/{dongle_id}/stats")


@mcp.tool()
def list_routes(dongle_id: str, days_back: int = 7) -> Any:
    """List route segments recorded in the last N days, newest first.

    A route is one ignition-to-power-down drive, named 'dongleid|YYYY-MM-DD--HH-MM-SS'.
    Each segment is roughly one minute, so a 30-minute drive is about 30 segments.
    Widen days_back if nothing comes back; the device only uploads on WiFi.
    """
    if days_back < 1:
        raise DeviceError("days_back must be at least 1.")
    now_ms = int(time.time() * 1000)
    from_ms = now_ms - days_back * 86_400_000
    return _get(f"v1/devices/{dongle_id}/segments", params={"from": from_ms, "to": now_ms})


@mcp.tool()
def route_info(route_name: str) -> Any:
    """Get metadata for one route. Route names look like 'dongleid|YYYY-MM-DD--HH-MM-SS'."""
    return _get(f"v1/route/{route_name}/")


@mcp.tool()
def route_segments(route_name: str) -> Any:
    """List the segments belonging to a single route."""
    return _get(f"v1/route/{route_name}/segments")


@mcp.tool()
def route_files(route_name: str) -> Any:
    """Get signed download URLs for a route's logs and video.

    Returns short-lived URLs for rlogs, qlogs, and camera segments. Download rlogs
    from these URLs rather than pulling them off the device over SSH.

    Rate limited by comma to 5 requests per minute; this server enforces that locally
    and will tell you how long to wait rather than letting you hit a 429.
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
