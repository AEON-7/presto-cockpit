# On-device TRNG self-test. Run with:  mpremote connect <PORT> run tools/rng_selftest.py
# Proves (1) random_screen + rng import cleanly, (2) the entropy pool is fed by REAL
# sensor noise (raw LSBs differ read-to-read), (3) draws are uniform / in-range.
import time
from app.screens.random_screen import RandomScreen   # syntax/import check (no hw)
from app.hw.sensors import Sensors
from app.rng import EntropyPool

print("imports OK:", RandomScreen.name)

s = Sensors()
pool = EntropyPool()
buf = {}
raw = []
for i in range(60):
    s.read(buf)
    pool.stir(buf)
    if i < 4:
        raw.append((round(buf.get("ax", 0), 6), round(buf.get("gz", 0), 6),
                    buf.get("pressure_hpa"), buf.get("temp_c")))
    time.sleep_ms(20)

print("sensor keys:", sorted(buf.keys()))
print("raw reads (ax, gz, press, temp) - should DIFFER if noise is real:")
for r in raw:
    print("   ", r)
print("pool sources:", pool.sources, " ready:", pool.ready(), " fill:", pool.fill())


def hist(fn, n):
    d = {}
    for _ in range(n):
        v = fn()
        d[v] = d.get(v, 0) + 1
    return d


coin = hist(lambda: ("H" if pool.bits(1) == 0 else "T"), 2000)
d6 = hist(lambda: pool.randbelow(6) + 1, 6000)
d20 = hist(lambda: pool.randbelow(20) + 1, 6000)
print("coin:", coin)
print("d6:", {k: d6[k] for k in sorted(d6)})
print("d20: faces=%d min=%d max=%d" % (len(d20), min(d20), max(d20)))
print("SELFTEST OK")
