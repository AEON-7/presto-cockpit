# Hardware-free render test for RandomScreen: drives every draw() branch through a
# fake display and asserts nothing throws. Runs under CPython or on-device.
import sys
sys.path.insert(0, ".")

import time                                    # CPython lacks ticks_*; shim them for desktop runs
if not hasattr(time, "ticks_ms"):
    import time as _t
    time.ticks_ms = lambda: int(_t.monotonic() * 1000)
    time.ticks_add = lambda a, b: a + b
    time.ticks_diff = lambda a, b: a - b

from app.rng import EntropyPool
from app.screens.random_screen import RandomScreen, MODES


class FakeDisplay:
    def __init__(self):
        self.calls = 0
    def create_pen(self, *a):
        return ("pen", a)
    def set_pen(self, p):
        self.calls += 1
    def clear(self):
        pass
    def text(self, *a):
        self.calls += 1
    def rectangle(self, *a):
        self.calls += 1
    def circle(self, *a):
        self.calls += 1
    def measure_text(self, s, scale=1, *a):
        return len(s) * 6 * scale
    def get_bounds(self):
        return (480, 480)


class Obj:
    pass


ctx = Obj()
ctx.display = FakeDisplay()
ctx.W, ctx.H = 480, 480
ctx.state = Obj()
ctx.state.sensors = {"ax": 0.1, "gz": -0.2, "temp_c": 24.3, "pressure_hpa": 1009.3, "lux": 0, "prox": 3}
ctx.rng = EntropyPool()

scr = RandomScreen(ctx)
scr.draw()                                   # not-ready branch
print("render(not-ready) OK  calls=", ctx.display.calls)

for _ in range(20):
    ctx.rng.stir(ctx.state.sensors)
scr.draw()                                   # ready + idle (TAP TO ...)
print("render(idle) OK")

for m in range(4):
    scr._mode = m
    scr.on_touch(240, 250)                   # tap center -> roll
    scr.draw()                               # animating frame
    res = scr._result
    scr._anim_until = 0
    scr.draw()                               # settled frame
    print("  %-4s -> %s  OK" % (MODES[m], res))

before = scr._mode
scr.on_touch(scr._chips[1][0] + 2, scr._chips[1][1] + 2)   # tap a chip
print("chip tap: mode %d -> %d" % (before, scr._mode))
print("DRAW TEST OK")
