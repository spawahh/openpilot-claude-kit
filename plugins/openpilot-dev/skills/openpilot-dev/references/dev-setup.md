# openpilot dev environment, build, tools & logs

Source: `tools/README.md`, `docs/concepts/logs.md`, `README.md` on master, verified 2026-07-25. Verify live: `https://raw.githubusercontent.com/commaai/openpilot/master/tools/README.md`

## System requirements

- **Primary target: Ubuntu 24.04** (this is what's developed and tested on, aside from comma hardware)
- macOS: most of openpilot works natively
- Windows: use WSL 2 with the `Ubuntu-24.04` distribution — reported as near-seamless
  - WSL 2 UI/simulator performance issue? Set `export GALLIUM_DRIVER=d3d12` (add to `~/.bashrc`)
- Other systems: not recommended, will need modifications

## Setup (managed path)

```bash
git clone https://github.com/commaai/openpilot.git
cd openpilot
tools/op.sh setup          # managed dependency setup
source .venv/bin/activate  # python deps live in a uv-managed venv
scons -u                   # build
```

To manage dependencies manually instead, read the setup scripts in `tools/`.

## Running tests and lint

- Tests run via **pytest** (`-Werror --strict-config`), files named `test_*.py`, rooted at `openpilot/`
- Write tests **unittest-style** — importing `pytest` is a banned API
- Lint: **ruff** (2-space indent, 160 cols) + **codespell**
- Doc site development: `uv pip install .[docs]`, then `docs build` / `docs serve` from repo root

## Tools directory

Tool code lives under `openpilot/tools/`; the root `tools/` dir holds setup scripts and `op.sh`. Per-tool usage (commands, flags, workflows) is in `references/tools.md`.

| Tool | Purpose |
|---|---|
| `openpilot/tools/cabana/` | View and plot CAN messages, from recorded drives or live |
| `openpilot/tools/replay/` | Replay drives and mock openpilot services |
| `openpilot/tools/plotjuggler/` | Plot openpilot logs |
| `openpilot/tools/sim/` | Run openpilot in a simulator |
| `openpilot/tools/joystick/` | Control the car with a joystick |
| `openpilot/tools/webcam/` | Run openpilot on a PC with webcams |
| `openpilot/tools/camerastream/` | Stream cameras over the network |
| `openpilot/tools/serial/` | comma serial utilities |
| `openpilot/tools/lib/` | Libraries for reading logs — `openpilot/tools/lib/logreader.py` is the canonical Python log reader |
| `openpilot/tools/scripts/` | Misc scripts |

There's also a CTF (see `tools/` README) built for learning the tooling ecosystem.

## Log format

- Driving is recorded as **routes**, split into one-minute **segments**. A route runs ignition-on → ignition-off.
- Per segment:

| File | Contents |
|---|---|
| `rlog.zst` | All inter-process messages — zstd-compressed serialized Cap'n Proto. Service list: `openpilot/cereal/services.py` |
| `qlog.zst` | Decimated subset of rlog (decimation defined in `services.py`) — small enough to upload on slow connections |
| `fcamera.hevc` | Road camera, H.265 |
| `ecamera.hevc` | Wide road camera, H.265 |
| `dcamera.hevc` | Driver camera, H.265 |
| `qcamera.ts` | Low-res H.264 of road camera — what comma connect shows |

Read logs with `openpilot/tools/lib/logreader.py`; replay/view with `tools/replay` and `tools/cabana`.

## Branches

| Branch | What it is |
|---|---|
| `master` | Development; PRs target this |
| `nightly` | master, but built like a release — recommended for testers reporting issues |
| `release-mici` / `release-tizi` | Release branches (comma four / comma 3X), install URL `openpilot.comma.ai` |
| `release-*-staging` | Early access to upcoming releases, `openpilot-test.comma.ai` |

Quick install on device: enter a custom software URL during comma device setup (`openpilot.comma.ai` for release).
