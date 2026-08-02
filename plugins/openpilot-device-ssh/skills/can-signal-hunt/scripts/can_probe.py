#!/usr/bin/env python3
"""3-second read-only probe: is CAN flowing, and on which buses?"""
import time
from collections import Counter

from openpilot.cereal import messaging

sock = messaging.sub_sock('can', conflate=False, timeout=100)

n = 0
per_bus: Counter[int] = Counter()
addrs: set[tuple[int, int]] = set()

t0 = time.monotonic()
while time.monotonic() - t0 < 3.0:
  for msg in messaging.drain_sock(sock):
    for c in msg.can:
      n += 1
      per_bus[c.src] += 1
      addrs.add((c.src, c.address))
  time.sleep(0.005)

print(f"frames={n}  distinct_(bus,addr)={len(addrs)}")
print(f"per_bus={dict(sorted(per_bus.items()))}")
for want, name in ((372, "Engine_Stop_Start"), (912, "Dashlights")):
  buses = sorted({b for b, a in addrs if a == want})
  print(f"{name} (0x{want:03x}): {'buses ' + str(buses) if buses else 'NOT SEEN'}")
print("PROBE_DONE")
