---
name: openpilot-cloud-dev
description: >-
  Set up and work in an openpilot checkout (or a fork such as sunnypilot) inside an
  ephemeral cloud container or fresh Linux VM, with no comma device attached. Use when
  the environment needs provisioning (submodules, uv, scons), when a build or import
  fails in a container, when running car/safety tests headlessly, or when deciding
  whether a task is even possible without hardware. Trigger on "openpilot", "opendbc",
  "panda", "sunnypilot", "scons", "uv sync", "params_pyx", "raylib", "test_models",
  or setup failures in a cloud/codespace/devcontainer session.
---

# openpilot in a cloud container

Working knowledge for openpilot and its forks in an ephemeral environment — no local
Linux box, no comma device. The container is rebuilt every session, so provisioning
comes first, in order.

If this plugin's `SessionStart` hook ran, setup is already done and you can skip to
[Verify the environment](#verify-the-environment). The hook only fires when
`CLAUDE_CODE_REMOTE=true`, so a local session never triggers it.

**Before anything else, read [references/environment-limits.md](references/environment-limits.md).**
Most time lost in these containers goes to failures that look like a broken checkout but
are really environment constraints with known one-line answers.

## 1. Provision

Run from the checkout root.

```bash
# Submodules first — pyproject path-sources live inside them, so uv cannot
# resolve the lockfile until they exist.
git submodule update --jobs 4 --init --recursive

# Python env. Point uv at the system interpreter: the lockfile usually pins an
# exact 3.12.x with no python-build-standalone build available.
# --all-extras is REQUIRED (see environment-limits.md).
export UV_PYTHON_PREFERENCE=only-system
uv sync --frozen --python /usr/bin/python3.12 --all-extras
source .venv/bin/activate

# Build. Headless backend so the font-atlas step can run without a display.
# -k continues past UI-asset failures that do not affect Python imports.
export RAYLIB_BACKEND=headless
scons -j"$(nproc)" --minimal -k
```

Some forks ship `tools/setup_dependencies.sh`, which installs cross-distro build deps
and runs `uv sync` itself. Prefer it when present.

Drop `--minimal` only if you need the full UI or test binaries; it roughly doubles
build time and adds targets that fail without a display.

## Verify the environment

Never trust the scons exit code — `-k` masks real failures. Assert the artifacts:

```bash
# The import-critical extension must exist (path differs by fork layout).
ls common/params_pyx.so openpilot/common/params_pyx.so 2>/dev/null

# The two imports car and safety tests need.
python -c "from openpilot.selfdrive.pandad import can_capnp_to_list; \
from opendbc.safety.tests.libsafety import libsafety_py; libsafety_py.libsafety; print('ok')"
```

`libsafety` needs no scons — it self-compiles the opendbc safety C code with `cc` at
first import. Edits under `opendbc/safety/**` therefore take effect in the *next*
Python process, with no rebuild step.

## 2. Run tests

```bash
# One platform.
MAX_EXAMPLES=300 pytest selfdrive/car/tests/test_models.py -k "TOYOTA_COROLLA_TSS2" -q

# Parallel sweep across platforms.
MAX_EXAMPLES=150 pytest selfdrive/car/tests/test_models.py -n 8 --dist worksteal -q
```

- Route CAN logs download from openpilotci on first use and are cached. The first run
  per platform is slow; later runs are fast.
- `MAX_EXAMPLES` controls hypothesis example counts (default 300). Upstream CI runs a
  reduced smoke configuration; the full fuzz runs on comma's own infrastructure.
- `NUM_JOBS` / `JOB_ID` shard platforms across workers.

Two gotchas that waste real time — both covered in
[references/environment-limits.md](references/environment-limits.md): `pytest -k` matches
case-insensitively against the *whole* test id including the file path, and a stale
`.hypothesis/` directory replays old failing examples against new code and looks
exactly like flakiness.

## 3. Know what you cannot do here

A container has no CAN bus, no camera, no GPS, and no comma device. Before starting,
check the task against [references/environment-limits.md](references/environment-limits.md#what-a-container-cannot-do).
Work that needs a car or a device cannot be *validated* here, only drafted — say so
plainly rather than implying a change is verified.

## Safety

openpilot is driver-assistance software that actuates a real vehicle. Nothing built or
tested in a container is validated for road use. Passing tests here means the code
imports and behaves as specified in simulation — not that it is safe to drive. Never
describe a container-tested change as road-ready.
