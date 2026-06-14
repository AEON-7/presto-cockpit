# Shake calibration: measures accel-magnitude "jerk" at rest, during gentle
# handling, and during a hard shake, so we can pick a safe shake threshold.
# Reads at 10 Hz to match the app's sensor cadence (same EMA smoothing).
import time
import math
from presto import Presto
from app.hw.sensors import Sensors

p = Presto(full_res=True, ambient_light=False)
d = p.display
W, H = d.get_bounds()
BG = d.create_pen(8, 10, 16)
FG = d.create_pen(255, 111, 213)
DIM = d.create_pen(140, 140, 150)


def show(msg, sub=""):
    d.set_pen(BG); d.clear()
    d.set_pen(FG); d.text(msg, 24, 200, W, 5)
    if sub:
        d.set_pen(DIM); d.text(sub, 24, 270, W, 2)
    p.update()


s = Sensors()
buf = {}


def mag():
    s.read(buf)
    ax = buf.get("ax", 0) or 0
    ay = buf.get("ay", 0) or 0
    az = buf.get("az", 0) or 0
    return math.sqrt(ax * ax + ay * ay + az * az)


for _ in range(12):       # warm up the EMA
    mag(); time.sleep_ms(80)

phases = [("HOLD STILL", 6000), ("MOVE / PICK UP", 7000), ("SHAKE HARD!", 12000)]
prev = mag()
results = []
for name, dur in phases:
    show(name, "(%d s)" % (dur // 1000))
    print("PHASE:", name)
    peak_j = 0.0
    mn = mx = prev
    over = {8000: 0, 12000: 0, 16000: 0, 22000: 0}
    end = time.ticks_add(time.ticks_ms(), dur)
    while time.ticks_diff(end, time.ticks_ms()) > 0:
        m = mag()
        j = abs(m - prev); prev = m
        if j > peak_j:
            peak_j = j
        if m < mn:
            mn = m
        if m > mx:
            mx = m
        for thr in over:
            if j >= thr:
                over[thr] += 1
        time.sleep_ms(100)
    results.append((name, peak_j, mn, mx, over))
    print("   peak_jerk=%.0f  mag=[%.0f..%.0f]  frames>=thr %s" %
          (peak_j, mn, mx, over))

show("DONE", "see console")
print("=== CALIBRATION SUMMARY ===")
for name, pj, mn, mx, over in results:
    print("  %-15s peak_jerk=%8.0f  mag %0.0f..%0.0f  over=%s" % (name, pj, mn, mx, over))
print("CALIB DONE")
