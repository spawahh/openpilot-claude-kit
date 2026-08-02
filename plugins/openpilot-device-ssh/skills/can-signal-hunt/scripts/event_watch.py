#!/usr/bin/env python3
"""
Event-triggered CAN message detector: finds new addresses, novel payloads,
and sporadic arrivals that appear only when the driver performs an action.

READ ONLY. Subscribes to the 'can' socket. Transmits nothing.

Complements iss_watch.py, which diffs consecutive frames per address and so
cannot see a message that is sent ONLY on a button press with an identical
payload each time. This one looks for:

  1. NEW_ADDR      — an address never seen during baseline at all
  2. NOVEL_PAYLOAD — a payload never seen during baseline (low-entropy addrs)
  3. sporadic      — addresses arriving rarely/burstily, listed at the end

  event_watch.py baseline [secs]
  event_watch.py capture  [secs]
"""
import json
import signal
import sys
import time
from collections import Counter, defaultdict

from openpilot.cereal import messaging

BASE_PATH = "/data/iss_events_base.json"
ENTROPY_CAP = 64       # >this many distinct baseline payloads == too noisy to diff
PRINT_CAP = 12         # max novel-payload prints per address
DEFAULT_BASELINE = 30
DEFAULT_CAPTURE = 600


def stream(secs: float):
  sock = messaging.sub_sock('can', conflate=False, timeout=100)
  t0 = time.monotonic()
  while (t := time.monotonic() - t0) < secs:
    for msg in messaging.drain_sock(sock):
      for c in msg.can:
        if c.src > 2:            # skip openpilot's own TX echo
          continue
        yield t, c.src, c.address, bytes(c.dat)
    time.sleep(0.005)


def do_baseline(secs: float) -> None:
  print(f"BASELINE_START {secs:.0f}s — sit still, touch nothing", flush=True)
  counts: Counter[str] = Counter()
  payloads: dict[str, set[str]] = defaultdict(set)

  for _t, bus, addr, dat in stream(secs):
    k = f"{bus}:{addr}"
    counts[k] += 1
    p = payloads[k]
    if len(p) <= ENTROPY_CAP:
      p.add(dat.hex())

  hi = sorted(k for k, p in payloads.items() if len(p) > ENTROPY_CAP)
  out = {
    "counts": dict(counts),
    "payloads": {k: sorted(p) for k, p in payloads.items() if len(p) <= ENTROPY_CAP},
    "high_entropy": hi,
  }
  with open(BASE_PATH, "w") as f:
    json.dump(out, f)

  print(f"{len(counts)} addresses; {len(hi)} high-entropy (payload novelty "
        f"disabled for those)", flush=True)
  print("BASELINE_DONE", flush=True)


def do_capture(secs: float) -> None:
  with open(BASE_PATH) as f:
    base = json.load(f)
  known: set[str] = set(base["counts"])
  payloads: dict[str, set[str]] = {k: set(v) for k, v in base["payloads"].items()}
  high_entropy: set[str] = set(base["high_entropy"])

  arrivals: dict[str, list[float]] = defaultdict(list)
  printed: Counter[str] = Counter()
  new_addrs: set[str] = set()

  def summarise(*_a) -> None:
    print("", flush=True)
    print("=== sporadic addresses (<=10 arrivals) ===", flush=True)
    quiet = {k: v for k, v in arrivals.items() if len(v) <= 10}
    for k, times in sorted(quiet.items(), key=lambda kv: len(kv[1])):
      bus, addr = (int(x) for x in k.split(":"))
      stamps = " ".join(f"{t:.1f}" for t in times[:15])
      flag = "  NEW" if k in new_addrs else ""
      print(f"bus{bus} 0x{addr:03x} ({addr:4d}) x{len(times):<3} @ {stamps}{flag}",
            flush=True)
    if not quiet:
      print("(none — every address arrived >10 times)", flush=True)
    print("", flush=True)
    print(f"NEW_ADDRS_TOTAL={len(new_addrs)}", flush=True)
    print("CAPTURE_DONE", flush=True)
    sys.exit(0)

  signal.signal(signal.SIGTERM, summarise)
  signal.signal(signal.SIGINT, summarise)

  print(f"CAPTURE_OPEN — press whenever, up to {secs:.0f}s. "
        f"{len(known)} known addrs, {len(high_entropy)} high-entropy.", flush=True)

  for t, bus, addr, dat in stream(secs):
    k = f"{bus}:{addr}"
    arrivals[k].append(t)

    if k not in known:
      if k not in new_addrs:
        new_addrs.add(k)
        print(f"t={t:6.1f}  NEW_ADDR      bus{bus} 0x{addr:03x} ({addr:4d}) "
              f"{dat.hex()}", flush=True)
      continue

    if k in high_entropy:
      continue

    h = dat.hex()
    seen = payloads.setdefault(k, set())
    if h not in seen:
      seen.add(h)
      printed[k] += 1
      if printed[k] <= PRINT_CAP:
        tag = ""
        if addr == 372:
          tag = "  <-- Engine_Stop_Start"
        elif addr == 912:
          tag = "  <-- Dashlights"
        print(f"t={t:6.1f}  NOVEL_PAYLOAD bus{bus} 0x{addr:03x} ({addr:4d}) "
              f"{h}{tag}", flush=True)
      elif printed[k] == PRINT_CAP + 1:
        print(f"t={t:6.1f}  (suppressing further novelty on 0x{addr:03x})",
              flush=True)

  summarise()


if __name__ == "__main__":
  mode = sys.argv[1] if len(sys.argv) > 1 else "baseline"
  if mode == "baseline":
    do_baseline(float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_BASELINE)
  elif mode == "capture":
    do_capture(float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_CAPTURE)
  else:
    sys.exit(f"unknown mode {mode!r}")
