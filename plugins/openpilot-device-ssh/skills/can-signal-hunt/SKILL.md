---
name: can-signal-hunt
description: >-
  Find the CAN message and bit behind a physical car action — a dash button press, a
  setting toggle, an aftermarket module injecting a command — using a live comma
  device. Covers the baseline/capture method, offline correlation, and the false
  positives that produce confidently wrong answers. Use when asked which CAN message
  does X, to map an unmapped signal for a DBC, to sniff what a module transmits, or
  to prove a signal is NOT on a reachable bus.
---

# Hunting a CAN signal with a comma device

**Read-only throughout. Nothing here transmits to the car.**

Scripts live in `scripts/` next to this file. Push them to the device with base64 —
it avoids quoting problems — and run them there. Decoding cereal needs the device's
Python environment.

```bash
base64 -w0 scripts/event_watch.py | ssh comma@<ip> -i ~/.ssh/your_key \
  "base64 -d > /data/event_watch.py"
```

## The on-device environment

**The import is `from openpilot.cereal import messaging`.** A stale
`/data/openpilot/cereal/messaging/` holding only `__pycache__` shadows the real package
at `/data/openpilot/openpilot/cereal/`, so `import cereal.messaging` yields an *empty
namespace package* — `dir()` returns `[]` and `sub_sock` looks like it does not exist.

```bash
cd /data/openpilot && export PYTHONPATH=/data/openpilot:/data/openpilot/msgq_repo:\
/data/openpilot/opendbc_repo:/data/openpilot/rednose_repo:/data/openpilot/teleoprtc_repo:\
/data/openpilot/tinygrad_repo && /usr/local/venv/bin/python3 -u /data/event_watch.py capture 600
```

Run long captures in the background with a SIGTERM handler that prints a summary. Stop
with `pkill -TERM -f "event_wat[c]h"` — bracket a letter so the pattern misses the
invoking shell.

## Design the procedure so timing does not matter

**Do not try to cue the driver.** `soundd` owns ALSA card 0 device 0 while openpilot
runs, so `aplay` fails with "Device or resource busy", and `plughw:0,1` / `plughw:0,2`
reject the hw params. There is no way to beep at them.

Instead split into two phases: a **baseline** the driver sits still through, then an
**open-ended capture** they act in at their own pace. No clock to hit, no lost count.
Confirm CAN is flowing first with `can_probe.py` (3 s, reports frames per bus).

## Two detectors, because they see different things

| Script | Finds | Blind to |
|---|---|---|
| `bit_watch.py` | a bit changing inside a periodic message | a message sent *only* on the action |
| `event_watch.py` | new addresses, novel payloads, sporadic arrivals | a bit buried in high-entropy traffic |

Run both. `bit_watch.py` alone misses an event-triggered message carrying a constant
payload, because it diffs consecutive frames of the same address and every press looks
identical.

## Offline correlation is the real proof — `rlog_analyze.py`

openpilot records the whole session to rlog, so re-analyse without the driver present.

Establish **ground truth** press times from a signal already known to respond — a dash
indicator bit, for example — then score every other address against them. Supply it via
the `GROUND_TRUTH` environment variable as `addr:byte:mask`, comma separated:

```bash
GROUND_TRUTH="0x174:4:0xC0,0x390:6:0x40" \
  python3 rlog_analyze.py '/data/media/0/realdata/<route>--*/rlog*'
```

Four traps that produce confident wrong answers:

1. **"Hits every press" is meaningless alone.** High-rate messages hit all presses by
   chance inside a ±1 s window. A real signal has *low total changes, high hit ratio*.
   Always report a spurious count next to the hit count.
2. **A slow-periodic signal mimics a press pattern.** A "masked if more than 3 toggles in
   30 s" threshold lets anything with a period of roughly 8 s or more through, and it
   lands as a tidy "exactly 4 transitions". Discriminate by whether it **continues past
   the last press** — event-driven stops, periodic does not.
3. **Some "sporadic" addresses are openpilot itself.** The sporadic report surfaces
   `0x7xx` addresses arriving on a tidy ~31 s cycle. Those are openpilot's own UDS ECU
   polling responses, not the car reacting to anything. Discount the diagnostic range
   when it has a fixed period.
4. **Volatility classification granularity changes the answer, and the right choice is
   unsettled.** See below — read this before trusting a candidate list.

### Known open question: per-bit vs per-byte volatility

`rlog_analyze.py` classifies volatile bytes (counters, checksums) **per bit**, on the
reasoning that a button bit can share a byte with a counter nibble and byte-level
classification would discard it.

Field notes from an earlier run record the opposite conclusion: that bit-level admits
individual checksum bits — each flips in under 40% of frame pairs, so each passes the
volatility filter — and floods the candidate list, in one case taking a known-good
ground-truth signal from 9 spurious hits to 1360.

**Both effects are real and they pull in opposite directions.** The script ships with
per-bit classification. If your candidate list is implausibly long, switch the
classification to per-byte and compare — the loop is a few lines near
`# volatile classification`. Treat a candidate that survives both settings as much
stronger than one that survives only one.

## Interpreting a negative result

Absence of a correlating message means the action is not observable on the buses you
tapped. It does **not** mean no CAN mechanism exists.

A button wired discretely to a module, or on a body bus behind a gateway, broadcasts
only its *effect*. An aftermarket module may still command the same setting with a
message the button never sends — which this method cannot discover by watching presses,
and which sniffing that module *can*.

State the scope of a negative explicitly: "not present on buses 0–2 during this capture"
is a finding; "the car has no such message" is not something this method can establish.
