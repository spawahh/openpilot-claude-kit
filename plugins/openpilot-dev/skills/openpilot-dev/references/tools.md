# openpilot tools — usage guide

Source: per-tool READMEs under `openpilot/tools/` on master, verified 2026-07-25. Path note: tool *code* lives in `openpilot/tools/`; the root `tools/` directory holds environment setup (`op.sh`, setup scripts). Verify live, e.g.: `https://raw.githubusercontent.com/commaai/openpilot/master/openpilot/tools/replay/README.md`

## Common setup

- Authenticate once to access your routes from comma's servers: `python3 openpilot/tools/lib/auth.py`
- Route names come from connect.comma.ai, format `dongleid/routeid` (e.g. `5beb9b58bd12b691/0000010a--a51155e496`)
- Streaming from a comma device generally means: SSH in, run `cd /data/openpilot && ./openpilot/cereal/messaging/bridge`, then connect a PC tool over ZMQ

## replay — simulate a drive from logs

```bash
openpilot/tools/replay/replay <route-name>        # remote route from your account
openpilot/tools/replay/replay --demo              # built-in demo route
openpilot/tools/replay/replay <route> --data_dir="/path_to_routes"   # local route
ZMQ=1 openpilot/tools/replay/replay <route>       # publish over ZMQ instead of MSGQ
```

Useful flags: `-a/-b` allow/block service lists, `-s <seconds>` start offset, `-x <speed>` (0.2–3), `--dcam` / `--ecam` / `--qcam` extra cameras, `--no-loop`, `--auto` (best available source, no video).

Pair with:
- openpilot UI: run replay, then `cd openpilot/selfdrive/ui && ./ui.py`
- watch3 (all three cameras): `./replay --demo --dcam --ecam`, then `./watch3.py` from `openpilot/selfdrive/ui`
- PlotJuggler streaming: run replay, then `openpilot/tools/plotjuggler/juggle.py --stream`
- `can_replay.py`: replay CAN onto real hardware via a panda jungle

## cabana — CAN viewer / DBC editor

Views raw CAN data, edits DBC files with direct opendbc integration, loads routes from comma connect.

```bash
cabana --demo                     # demo route
cabana "<route-name>"             # specific route
cabana                            # no args → stream selector dialog
cabana --panda                    # live from a connected panda
cabana --zmq <device-ip>          # live from a comma device (run bridge on device first)
cabana --socketcan <dev>          # from a SocketCAN device
cabana --dbc <file>               # open with a specific DBC
```

Live streams are logged to `~/cabana_live_stream/` by default and can be replayed later from the stream selector.

## PlotJuggler — plot logs

Install plugins once: `cd openpilot/tools/plotjuggler && ./juggle.py --install`

```bash
./juggle.py "<route>"                      # whole route
./juggle.py "<route>/1"                    # one segment
./juggle.py "<route>/1/q"                  # qlogs instead of rlogs
./juggle.py "<route>/0:1"                  # segment range
./juggle.py --demo --layout=layouts/tuning.xml
./juggle.py --can --dbc <name> "<route>"   # parse CAN data
```

Streaming from car: device hotspot + bridge on device, then `ZMQ=1 ./juggle.py --stream` and start the `Cereal Subscriber` plugin. From a local replay: just `./juggle.py --stream`.

**Contribution tie-in:** the `layouts/tuning.xml` layout is the standard way to generate before/after plots for tuning PRs (required justification). Useful layouts are welcome upstream.

## LogReader — programmatic log access

```python
from openpilot.tools.lib.route import Route
from openpilot.tools.lib.logreader import LogReader

r = Route("a2a0ccea32023010|2023-07-27--13-01-19")
r.log_paths(); r.camera_paths()

lr = LogReader(r.log_paths()[0])
for msg in lr:
  if msg.which() == "carState":
    print(msg.carState.steeringAngleDeg)
```

Segment-range syntax: `dongle|timestamp / selector / query-type`

```python
LogReader(".../4")     # 4th segment        LogReader(".../4:6")  # segments 4–5
LogReader(".../-1")    # last segment       LogReader(".../:5")   # first 5
LogReader(".../4/q")   # qlogs              LogReader(".../4/r")  # rlogs (default)
```

## sim — MetaDrive simulator

```bash
./openpilot/tools/sim/launch_openpilot.sh   # start openpilot
./run_bridge.py                             # from openpilot/tools/sim — start bridge
```

Bridge flags: `--joystick`, `--high_quality`, `--dual_camera`. Keys: `1` resume/accel, `2` set/decel, `3` cancel, `r` reset, `i` ignition, `q` quit, `wasd` manual, `S` disengage (simulated brake).

## joystick — control debugging

Car off / openpilot offroad first.
- Keyboard on device: SSH in, `openpilot/tools/joystick/joystick_control.py --keyboard` (WASD, 5% increments)
- Joystick on laptop over network: set `JoystickDebugMode` param on device (`echo -n "1" > /data/params/d/JoystickDebugMode`), run `bridge {LAPTOP_IP} testJoystick` on device, then `ZMQ=1 joystick_control.py` on laptop. Panda must allow controls (cruise engaged).

## camerastream — remote camera viewing

On device (SSH, separate processes): `bridge`, `encoderd`, `camerad`. On PC: `openpilot/tools/camerastream/compressed_vipc.py <device-ip>` to decode onto VisionIPC, then `watch3.py` to display. **Device and PC must be on the same openpilot commit.**

## Quick workflow picker

| Goal | Tool chain |
|---|---|
| "What was openpilot doing at minute 12 of my drive?" | replay + UI, or PlotJuggler on that segment |
| Reverse-engineer / label CAN signals | cabana (+ DBC saved to opendbc fork) |
| Tuning PR evidence plots | PlotJuggler `layouts/tuning.xml`, before/after |
| Scripted analysis over many drives | LogReader with segment ranges (qlogs for speed) |
| Test control logic without a car | sim (MetaDrive) or joystick mode |
| Watch device cameras live from desk | camerastream + watch3 |
