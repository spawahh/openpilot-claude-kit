#!/usr/bin/env python3
"""
Passive CAN bit-transition watcher: finds a bit that changes inside a
periodic message when the driver performs an action.

READ ONLY. Subscribes to the 'can' socket. Transmits nothing.

  iss_watch.py baseline [secs]   learn self-toggling bits, save mask to JSON
  iss_watch.py capture  [secs]   stream every non-noisy transition, timestamped

Two phases so there is no timing pressure: press whenever you like during
capture. A bit only gets masked if it toggled MORE than NOISE_MAX times in
baseline, so one accidental press during baseline won't hide the button.
"""
import json
import signal
import sys
import time
from collections import Counter, defaultdict

from openpilot.cereal import messaging

MASK_PATH = "/data/iss_mask.json"
NOISE_MAX = 3          # >this many baseline toggles == self-toggling, mask it
DEFAULT_BASELINE = 30
DEFAULT_CAPTURE = 600


def bits_changed(prev: bytes, cur: bytes) -> list[int]:
  out = []
  for i in range(min(len(prev), len(cur))):
    x = prev[i] ^ cur[i]
    if x:
      for j in range(8):
        if (x >> j) & 1:
          out.append(i * 8 + j)
  return out


def stream(secs: float):
  """Yield (t, bus, addr, bit) for every bit transition seen."""
  sock = messaging.sub_sock('can', conflate=False, timeout=100)
  last: dict[tuple[int, int], bytes] = {}
  t0 = time.monotonic()
  while (t := time.monotonic() - t0) < secs:
    for msg in messaging.drain_sock(sock):
      for c in msg.can:
        if c.src > 2:            # skip openpilot's own TX echo
          continue
        key = (c.src, c.address)
        cur = bytes(c.dat)
        prev = last.get(key)
        last[key] = cur
        if prev is None or len(prev) != len(cur):
          continue
        for b in bits_changed(prev, cur):
          yield t, c.src, c.address, b
    time.sleep(0.005)


def do_baseline(secs: float) -> None:
  print(f"BASELINE_START {secs:.0f}s — sit still, touch nothing", flush=True)
  counts: Counter[str] = Counter()
  for _t, bus, addr, bit in stream(secs):
    counts[f"{bus}:{addr}:{bit}"] += 1

  mask = sorted(k for k, v in counts.items() if v > NOISE_MAX)
  quiet = {k: v for k, v in counts.items() if v <= NOISE_MAX}
  with open(MASK_PATH, "w") as f:
    json.dump({"mask": mask, "quiet": quiet}, f)

  print(f"masked {len(mask)} self-toggling bits", flush=True)
  if quiet:
    print(f"NOTE {len(quiet)} bit(s) toggled 1-{NOISE_MAX}x in baseline "
          f"— kept as candidates:", flush=True)
    for k, v in sorted(quiet.items(), key=lambda kv: -kv[1])[:10]:
      bus, addr, bit = (int(x) for x in k.split(":"))
      print(f"  bus{bus} 0x{addr:03x} byte{bit // 8} bit{bit % 8} x{v}", flush=True)
  print("BASELINE_DONE", flush=True)


def do_capture(secs: float) -> None:
  with open(MASK_PATH) as f:
    mask = set(json.load(f)["mask"])

  events: dict[str, list[float]] = defaultdict(list)

  def summarise(*_a) -> None:
    print("", flush=True)
    print("=== summary: fewest transitions first ===", flush=True)
    for k, times in sorted(events.items(), key=lambda kv: len(kv[1])):
      bus, addr, bit = (int(x) for x in k.split(":"))
      stamps = " ".join(f"{t:.1f}" for t in times[:15])
      print(f"bus{bus} 0x{addr:03x} ({addr:4d}) byte{bit // 8} bit{bit % 8} "
            f"x{len(times):<3} @ {stamps}", flush=True)
    if not events:
      print("NO TRANSITIONS — every changed bit was masked as noisy.", flush=True)
    print("CAPTURE_DONE", flush=True)
    sys.exit(0)

  signal.signal(signal.SIGTERM, summarise)
  signal.signal(signal.SIGINT, summarise)

  print(f"CAPTURE_OPEN — press whenever, up to {secs:.0f}s. "
        f"{len(mask)} bits masked.", flush=True)
  for t, bus, addr, bit in stream(secs):
    k = f"{bus}:{addr}:{bit}"
    if k in mask:
      continue
    events[k].append(t)
    tag = ""
    if addr == 372:
      tag = "  <-- Engine_Stop_Start"
    elif addr == 912:
      tag = "  <-- Dashlights"
    print(f"t={t:6.1f}  bus{bus} 0x{addr:03x} ({addr:4d}) "
          f"byte{bit // 8} bit{bit % 8}{tag}", flush=True)

  summarise()


if __name__ == "__main__":
  mode = sys.argv[1] if len(sys.argv) > 1 else "baseline"
  if mode == "baseline":
    do_baseline(float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_BASELINE)
  elif mode == "capture":
    do_capture(float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_CAPTURE)
  else:
    sys.exit(f"unknown mode {mode!r}")
