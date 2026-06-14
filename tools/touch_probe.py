# Live touch probe: shows a target, logs any real touch for 40s.
import time
from presto import Presto

p = Presto(full_res=True, ambient_light=False)
d = p.display
W, H = d.get_bounds()
BG = d.create_pen(8, 10, 16)
FG = d.create_pen(255, 111, 213)
d.set_pen(BG); d.clear()
d.set_pen(FG)
d.text("TAP THE SCREEN", 60, 190, W, 4)
d.text("(probe running ~40s)", 90, 250, W, 2)
p.update()

t = p.touch
print("PROBE START - tap the screen now")
frames = 0
xs = []
ys = []
last = None
hb = time.ticks_ms()
end = time.ticks_add(time.ticks_ms(), 40000)
while time.ticks_diff(end, time.ticks_ms()) > 0:
    p.touch_poll()
    a = p.touch_a
    state = getattr(t, "state", None)
    snap = (a.x, a.y, a.touched, state)
    if snap != last:
        if a.touched or (state not in (0, None)):
            print("TOUCH a=(x=%s y=%s touched=%s) ft_state=%s ft_xy=(%s,%s)" %
                  (a.x, a.y, a.touched, state, getattr(t, "x", None), getattr(t, "y", None)))
            frames += 1
            xs.append(a.x); ys.append(a.y)
        last = snap
    if time.ticks_diff(time.ticks_ms(), hb) > 5000:
        print("...alive, touch-frames so far:", frames)
        hb = time.ticks_ms()
    time.sleep_ms(25)

if xs:
    print("RESULT: %d touch-frames; x %d..%d  y %d..%d" % (frames, min(xs), max(xs), min(ys), max(ys)))
else:
    print("RESULT: NO touches detected at all (touched never True, ft_state never changed)")
print("PROBE DONE")
