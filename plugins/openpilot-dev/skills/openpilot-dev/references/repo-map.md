# openpilot repo map

Verified against master 2026-07-25. The layout migrates over time (e.g., car code moving to opendbc) — verify live via the GitHub API or raw files when a path matters.

## Root layout

```
openpilot/                 # the python package (see below)
tools/                     # env setup only (op.sh, setup scripts)
docs/                      # source for docs.comma.ai (zensical)
scripts/                   # repo maintenance scripts
SConstruct                 # scons build entry point
pyproject.toml, uv.lock    # deps (uv), ruff/pytest/codespell config
launch_openpilot.sh        # on-device launch chain
Jenkinsfile                # hardware-in-the-loop CI
```

## Submodules / sibling repos

| Path | Repo | Role |
|---|---|---|
| `panda` | commaai/panda | CAN interface hardware + safety firmware |
| `opendbc_repo` | commaai/opendbc | **All car-specific code**: DBCs, car interfaces, safety modes + safety tests |
| `msgq_repo` | commaai/msgq | Pub/sub IPC messaging |
| `rednose_repo` | commaai/rednose | Kalman filter library (localization) |
| `tinygrad_repo` | tinygrad/tinygrad | NN inference for the driving model |
| `teleoprtc_repo` | commaai/teleoprtc | WebRTC teleoperation |

## The `openpilot/` package

```
openpilot/
├── cereal/       # message schemas (Cap'n Proto) + services.py registry
├── common/       # shared utilities (params, realtime helpers, ...)
├── selfdrive/    # the driving stack (below)
├── system/       # OS-level services (camerad, loggerd, ui libs, updated, ...)
└── tools/        # THE dev/debug tools: cabana, replay, plotjuggler, sim, joystick, camerastream, lib/logreader.py
```

## `openpilot/selfdrive/` — the driving stack

| Dir | Role |
|---|---|
| `car/` | Residual car-specific glue (`car_specific.py` event logic) — being migrated to opendbc |
| `controls/` | Lateral/longitudinal control (controlsd and friends) |
| `locationd/` | Localization, calibration, parameter estimation |
| `modeld/` | Driving + monitoring model runners |
| `monitoring/` | Driver monitoring — forks must not weaken this |
| `pandad/` | Interface to the panda |
| `selfdrived/` | State machine, events, alerts; `helpers.py` holds excessive-actuation checks |
| `ui/` | On-device UI |
| `test/` | Process replay and integration tests |

## Where does my change belong?

- Car support (interfaces, CAN, tuning values, safety) → **opendbc**, not here. Structure per brand: `opendbc/car/[brand]/{interface,carstate,carcontroller,[brand]can,values,radar_interface}.py`; safety in `opendbc/safety/modes/[brand].h` + mandatory `opendbc/safety/tests/test_[brand].py`.
- Firmware/USB/CAN hardware behavior → panda
- Message schema additions → `openpilot/cereal` (stock structs must not be repurposed; add new ones)
- Docs → `docs/` (published to docs.comma.ai on push to master)
- A car port how-to lives at `docs/how-to/car-port.md`; brand ports vs. model ports are distinguished there (model ports are much easier).
