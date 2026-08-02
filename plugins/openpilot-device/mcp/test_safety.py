# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Prove the openpilot-device server is read-only by construction.

Runs with no dependencies and no network: the mcp and httpx imports are stubbed, so
this exercises the guard, throttle, and token logic in isolation.

    python test_safety.py
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path

SERVER = Path(__file__).with_name("server.py")


def _stub_imports() -> None:
    """Stand in for mcp and httpx so server.py imports without either installed."""
    fastmcp = types.ModuleType("mcp.server.fastmcp")

    class FastMCP:
        def __init__(self, name: str) -> None:
            self.name = name
            self.tools: list[str] = []

        def tool(self, *_a, **_k):
            def deco(fn):
                self.tools.append(fn.__name__)
                return fn
            return deco

        def run(self) -> None:  # pragma: no cover - never called in tests
            pass

    fastmcp.FastMCP = FastMCP
    server_mod = types.ModuleType("mcp.server")
    server_mod.fastmcp = fastmcp
    root = types.ModuleType("mcp")
    root.server = server_mod
    sys.modules.update({"mcp": root, "mcp.server": server_mod, "mcp.server.fastmcp": fastmcp})

    if importlib.util.find_spec("httpx") is None:
        httpx = types.ModuleType("httpx")

        class HTTPStatusError(Exception):
            def __init__(self, *_a, response=None, **_k):
                self.response = response

        class RequestError(Exception):
            pass

        class Client:
            def __init__(self, **_k): pass
            def __enter__(self): return self
            def __exit__(self, *_a): return False

        httpx.HTTPStatusError = HTTPStatusError
        httpx.RequestError = RequestError
        httpx.Client = Client
        sys.modules["httpx"] = httpx


def _load():
    spec = importlib.util.spec_from_file_location("opserver", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Endpoints that exist on the comma API and must stay unreachable. Cancelling a prime
# subscription or pushing a destination to a moving car must never be one argument away.
FORBIDDEN_PATHS = [
    "v1/prime/cancel",
    "v1/prime/pay",
    "v1/prime/payment_source",
    "v2/pilotpair/",
    "v1/devices/abc/unpair",
    "v1/devices/abc/add_user",
    "v1/devices/abc/del_user",
    "v1/navigation/abc/set_destination",
    "v1/navigation/abc/locations",
]

ALLOWED_PATHS = [
    "v1/me/",
    "v1/me/devices/",
    "v1.1/devices/abc/",
    "v1.1/devices/abc/stats",
    "v1/devices/abc/segments",
    "v1/route/abc|2026-01-01--00-00-00/files",
    "v1/devices/abc/bootlogs",
    "v1/devices/abc/crashlogs",
]

# A tool whose name implies a state change should never appear in this server.
MUTATING_WORDS = ("set_", "delete", "cancel", "pay", "unpair", "reboot", "write", "upload")

EXPECTED_TOOL_COUNT = 13


def main() -> int:
    _stub_imports()
    m = _load()
    failures: list[str] = []

    def check(label: str, ok: bool) -> None:
        print(("PASS  " if ok else "FAIL  ") + label)
        if not ok:
            failures.append(label)

    check(
        f"{EXPECTED_TOOL_COUNT} tools registered (got {len(m.mcp.tools)})",
        len(m.mcp.tools) == EXPECTED_TOOL_COUNT,
    )

    for path in FORBIDDEN_PATHS:
        try:
            m._guard_path(path)
            check(f"guard blocks {path}", False)
        except m.DeviceError:
            check(f"guard blocks {path}", True)

    for path in ALLOWED_PATHS:
        try:
            m._guard_path(path)
            check(f"guard allows {path}", True)
        except m.DeviceError:
            check(f"guard allows {path}", False)

    os.environ.pop("COMMA_JWT", None)
    try:
        m._token()
        check("missing COMMA_JWT raises", False)
    except m.DeviceError as exc:
        check("missing COMMA_JWT points at jwt.comma.ai", "jwt.comma.ai" in str(exc))

    os.environ["COMMA_JWT"] = "  tok123  "
    check("token read from env and stripped", m._token() == "tok123")

    m._files_calls.clear()
    for _ in range(m.FILES_RATE_LIMIT):
        m._throttle_files()
    try:
        m._throttle_files()
        check("files call past the limit is blocked", False)
    except m.DeviceError as exc:
        check("files call past the limit reports a wait", "Retry in" in str(exc))

    try:
        m.list_routes("abc", days_back=0)
        check("days_back=0 rejected", False)
    except m.DeviceError:
        check("days_back=0 rejected", True)

    named_mutations = [t for t in m.mcp.tools if any(w in t.lower() for w in MUTATING_WORDS)]
    check(f"no mutating tool names (found {named_mutations})", not named_mutations)

    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
