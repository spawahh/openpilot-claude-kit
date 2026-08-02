# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Launch the server the way .mcp.json does and speak MCP to it over stdio.

Covers the layer no other test reaches: uv resolving the PEP 723 dependency block,
server.py importing under the resolved interpreter, and the tools registering with
usable descriptions.

Needs `uv` on PATH. Does NOT need a credential — tools/list never calls the API.
The first run resolves dependencies and can take a minute.

    python test_startup.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

SERVER = Path(__file__).with_name("server.py")
PROTOCOL_VERSION = "2024-11-05"
STARTUP_TIMEOUT = 180

EXPECTED_TOOLS = {
    "verify_connection", "list_devices", "device_info", "device_stats",
    "list_routes", "list_segments", "route_info", "route_files",
    "device_bootlogs", "device_crashlogs", "live_message",
    "device_runtime_state", "list_device_files",
}


def main() -> int:
    if not any(
        os.access(os.path.join(d, f"uv{ext}"), os.X_OK)
        for d in os.environ.get("PATH", "").split(os.pathsep) if d
        for ext in ("", ".exe")
    ):
        print("SKIP  uv not on PATH; cannot test server startup")
        return 0

    cmd = ["uv", "run", "--quiet", str(SERVER)]
    print(f"launching: {' '.join(cmd)}")

    env = dict(os.environ)
    # tools/list never calls the API, so any placeholder is fine here. Using one
    # keeps the test independent of whether a real token happens to be set.
    env["COMMA_JWT"] = "placeholder-unused-by-tools-list"

    started = time.time()
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", env=env,
    )
    failures: list[str] = []

    def send(payload: dict) -> None:
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()

    def read(timeout: int = STARTUP_TIMEOUT) -> dict | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue  # uv or the SDK may emit non-JSON chatter
        return None

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "kit-verify", "version": "1"}}})
        init = read()
        if not init or "result" not in init:
            print(f"FAIL  initialize -> {str(init)[:300]}")
            failures.append("initialize")
            return 1
        print(f"PASS  initialize ({time.time() - started:.1f}s)")

        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        listed = read(60)
        tools = (listed or {}).get("result", {}).get("tools", [])
        names = {t["name"] for t in tools}

        missing, extra = EXPECTED_TOOLS - names, names - EXPECTED_TOOLS
        if missing or extra:
            print(f"FAIL  tool set mismatch: missing={sorted(missing)} extra={sorted(extra)}")
            failures.append("tool set")
        else:
            print(f"PASS  all {len(EXPECTED_TOOLS)} expected tools registered")

        undocumented = sorted(t["name"] for t in tools if not t.get("description", "").strip())
        if undocumented:
            print(f"FAIL  tools missing a description: {undocumented}")
            failures.append("descriptions")
        else:
            print("PASS  every tool has a description")
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        if failures:
            stderr = proc.stderr.read().strip()
            if stderr:
                print("\n--- server stderr (last 15 lines) ---")
                print("\n".join(stderr.splitlines()[-15:]))

    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
