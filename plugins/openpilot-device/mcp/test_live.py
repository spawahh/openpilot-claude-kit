# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.2.0", "httpx>=0.27"]
# ///
"""Exercise every tool against the live comma API.

Requires a real COMMA_JWT in the environment, so it cannot run in CI. Use it to
confirm the API has not drifted, or after changing an endpoint.

    uv run test_live.py

Prints outcomes and shapes only — never coordinates, VIN, email, or the token.
Athena tools are expected to fail when the device is offline; the test asserts the
failure is the clear "not currently connected" message rather than a raw 404.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

SERVER = pathlib.Path(__file__).with_name("server.py")

spec = importlib.util.spec_from_file_location("opserver", SERVER)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

failures: list[str] = []


def run(label, fn):
    try:
        result = fn()
        print(f"PASS  {label}")
        return result
    except Exception as exc:
        print(f"FAIL  {label}\n        {type(exc).__name__}: {str(exc)[:200]}")
        failures.append(label)
        return None


def main() -> int:
    vc = run("verify_connection", m.verify_connection)
    if not vc or not vc.get("devices"):
        print("\ncannot continue without a reachable account")
        return 1

    dev = vc["devices"][0]
    dongle = dev["dongle_id"]
    print(f"        online={dev['online']} last_seen={dev['last_seen_seconds_ago']}s "
          f"type={dev['device_type']}")

    devices = run("list_devices", m.list_devices)
    if devices:
        leaked = [f for f in m.SENSITIVE_FIELDS if f in devices[0]]
        if leaked:
            print(f"FAIL  redaction leaked {leaked}")
            failures.append("redaction")
        else:
            print("PASS  redaction stripped location fields from live data")

    run("device_info", lambda: m.device_info(dongle))
    run("device_stats", lambda: m.device_stats(dongle))

    routes = run("list_routes", lambda: m.list_routes(dongle, days_back=30))
    if routes:
        print(f"        {len(routes)} routes in 30 days")
        name = routes[0]["fullname"]
        run("route_info", lambda: m.route_info(name))
        files = run("route_files", lambda: m.route_files(name))
        if files:
            print("        " + "  ".join(f"{k}={len(v)}" for k, v in files.items()))
            if not files.get("logs"):
                print("        note: 'logs' empty - full rlogs not uploaded for this route")

    segs = run("list_segments", lambda: m.list_segments(dongle, days_back=30))
    if segs:
        print(f"        {len(segs)} segments")

    run("device_bootlogs", lambda: m.device_bootlogs(dongle))
    run("device_crashlogs", lambda: m.device_crashlogs(dongle))

    print("\n--- athena (needs the device online) ---")
    online = dev["online"]
    for label, fn in (("live_message", lambda: m.live_message(dongle, "carState")),
                      ("list_device_files", lambda: m.list_device_files(dongle))):
        try:
            fn()
            print(f"PASS  {label} (device online)")
        except m.DeviceError as exc:
            if not online and "not currently connected" in str(exc):
                print(f"PASS  {label} - offline, reported clearly")
            else:
                print(f"FAIL  {label}: {str(exc)[:160]}")
                failures.append(label)

    run("device_runtime_state", lambda: m.device_runtime_state(dongle))

    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
