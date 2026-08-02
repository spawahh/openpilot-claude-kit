#!/usr/bin/env python3
"""
Rigorous offline pass over a recorded route: does ANY message correlate with
the action you are hunting?

You supply GROUND TRUTH — one or more signals already known to respond to the
action, for example a dash indicator bit. Their transitions define "a press
happened"; every other address is then scored against those times.

Set ground truth with the GROUND_TRUTH environment variable as a comma-separated
list of addr:byte:mask, all hex or decimal:

  GROUND_TRUTH="0x174:4:0xC0,0x390:6:0x40" python3 rlog_analyze.py '<glob>'

That example is a Subaru idle-stop-start hunt: Engine_Stop_Start 0x174
STOP_START_STATE byte 4 bits 6-7, and Dashlights 0x390 STOP_START byte 6 bit 6.
Substitute the signals for your own car and action.

Method, per (bus, addr):
  1. Classify each byte as volatile (checksum/counter) if it changes in more
     than VOLATILE_FRAC of consecutive frame pairs. Ignore those bytes.
  2. Collect change timestamps for the remaining stable bits.
  3. Score against the press clusters: how many presses it fires near, and how
     many times it fires when nothing was pressed.

A real button message hits every press and fires almost never otherwise.
"""
import glob
import os
import sys
from collections import defaultdict

from openpilot.tools.lib.logreader import LogReader

VOLATILE_FRAC = 0.40     # byte changing this often == counter/checksum
PRESS_MERGE = 0.5        # state edges closer than this == one press
WINDOW = 1.0             # a change this close to a press counts as a hit

# Signals already known to respond to the action, used to derive press times.
# Format: addr:byte:mask, comma separated. See the module docstring.
DEFAULT_GROUND_TRUTH = "0x174:4:0xC0,0x390:6:0x40"


def parse_ground_truth(spec: str) -> dict[int, tuple[int, int]]:
  """Parse 'addr:byte:mask,...' into {addr: (byte, mask)}."""
  out: dict[int, tuple[int, int]] = {}
  for entry in (e.strip() for e in spec.split(",") if e.strip()):
    parts = entry.split(":")
    if len(parts) != 3:
      sys.exit(f"bad GROUND_TRUTH entry {entry!r}; expected addr:byte:mask")
    try:
      addr, byte, mask = (int(p, 0) for p in parts)
    except ValueError:
      sys.exit(f"bad GROUND_TRUTH entry {entry!r}; values must be integers")
    out[addr] = (byte, mask)
  if not out:
    sys.exit("GROUND_TRUTH is empty; supply at least one addr:byte:mask")
  return out


GROUND_TRUTH_SIGNALS = parse_ground_truth(os.environ.get("GROUND_TRUTH", DEFAULT_GROUND_TRUTH))


def main(route_glob: str) -> None:
  paths = sorted(glob.glob(route_glob))
  if not paths:
    sys.exit(f"no segments matched {route_glob!r}")
  print(f"segments: {len(paths)}", flush=True)

  frames: dict[tuple[int, int], list[tuple[float, bytes]]] = defaultdict(list)
  t0 = None
  bad = 0

  for p in paths:
    try:
      for msg in LogReader(p):
        if msg.which() != 'can':
          continue
        t = msg.logMonoTime / 1e9
        if t0 is None:
          t0 = t
        for c in msg.can:
          if c.src > 2:
            continue
          frames[(c.src, c.address)].append((t - t0, bytes(c.dat)))
    except Exception as e:                       # truncated final segment etc.
      bad += 1
      print(f"  skipped {p.split('/')[-2]}: {type(e).__name__}", flush=True)

  print(f"parsed {sum(len(v) for v in frames.values())} frames, "
        f"{len(frames)} addresses, {bad} bad segment(s)", flush=True)
  if not frames:
    sys.exit("no CAN frames parsed")

  # ---- ground truth press times -------------------------------------------
  edges: list[float] = []
  for (_bus, addr), seq in frames.items():
    if addr not in GROUND_TRUTH_SIGNALS:
      continue
    idx, mask = GROUND_TRUTH_SIGNALS[addr]
    prev = None
    for t, d in seq:
      if len(d) <= idx:
        continue
      v = d[idx] & mask
      if prev is not None and v != prev:
        edges.append(t)
      prev = v

  edges.sort()
  presses: list[float] = []
  for t in edges:
    if not presses or t - presses[-1] > PRESS_MERGE:
      presses.append(t)
  print(f"press clusters from ground-truth state: {len(presses)}", flush=True)
  print("  at " + " ".join(f"{t:.1f}" for t in presses), flush=True)
  if not presses:
    sys.exit("no ground-truth state transitions found — cannot correlate")

  def near_press(t: float) -> bool:
    return any(abs(t - p) <= WINDOW for p in presses)

  # ---- score every other address ------------------------------------------
  rows = []
  for (bus, addr), seq in sorted(frames.items()):
    if len(seq) < 4:
      continue
    n = min(len(d) for _t, d in seq)
    if n == 0:
      continue

    # volatile classification, per BIT (a button bit can share a byte with a
    # counter nibble, so byte-level classification would discard it)
    changes = [0] * (n * 8)
    for i in range(1, len(seq)):
      a, b = seq[i - 1][1], seq[i][1]
      for j in range(n):
        x = a[j] ^ b[j]
        if x:
          for k in range(8):
            if (x >> k) & 1:
              changes[j * 8 + k] += 1
    pairs = len(seq) - 1
    stable = [q for q in range(n * 8) if 0 < changes[q] <= VOLATILE_FRAC * pairs]
    if not stable:
      continue

    # stable-bit change times
    hit_presses: set[int] = set()
    outside = 0
    total = 0
    for i in range(1, len(seq)):
      t, cur = seq[i]
      prev = seq[i - 1][1]
      if any(((prev[q // 8] ^ cur[q // 8]) >> (q % 8)) & 1 for q in stable):
        total += 1
        if near_press(t):
          for k, p in enumerate(presses):
            if abs(t - p) <= WINDOW:
              hit_presses.add(k)
        else:
          outside += 1
    if total == 0:
      continue
    rows.append((len(hit_presses), outside, total, bus, addr, stable))

  rows.sort(key=lambda r: (-r[0], r[1]))
  print("", flush=True)
  print(f"=== correlation vs {len(presses)} presses "
        f"(hits / spurious / total changes) ===", flush=True)
  for hits, outside, total, bus, addr, stable in rows[:25]:
    tag = "  <-- GROUND TRUTH" if addr in GROUND_TRUTH_SIGNALS else ""
    bits = ",".join(f"b{q // 8}.{q % 8}" for q in stable[:6])
    print(f"bus{bus} 0x{addr:03x} ({addr:4d})  hits {hits}/{len(presses)}  "
          f"spurious {outside:<5} total {total:<5} [{bits}]{tag}", flush=True)

  # A real button fires on (nearly) every press and almost never otherwise.
  # Hitting every press while firing thousands of times is chance, not signal.
  print("", flush=True)
  strong = [r for r in rows
            if r[4] not in GROUND_TRUTH_SIGNALS and r[0] >= len(presses) - 1 and r[1] <= 3 * len(presses)]
  if strong:
    print(f"CANDIDATES: {len(strong)} non-ground-truth address(es) fire on nearly every "
          f"press with low spurious rate:", flush=True)
    for hits, outside, total, bus, addr, _s in strong:
      print(f"  bus{bus} 0x{addr:03x} ({addr:4d}) hits {hits} spurious {outside} "
            f"total {total}", flush=True)
  else:
    print("NO CANDIDATE: every non-ground-truth address that hits all presses also fires "
          "hundreds-to-thousands of times unprompted (chance, not correlation).",
          flush=True)
  print("ANALYZE_DONE", flush=True)


if __name__ == "__main__":
  if len(sys.argv) < 2:
    sys.exit(
      "usage: rlog_analyze.py '<segment glob>'\n"
      "  on-device example: '/data/media/0/realdata/<route>--*/rlog*'\n"
      "  list routes with:  ls /data/media/0/realdata/"
    )
  main(sys.argv[1])
