"""Self-contained full-screen animations that also drive the back LEDs."""
import math
import time


def _hsv_rgb(h, s, v):
    i = int(h * 6) % 6
    f = h * 6 - int(h * 6)
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    r, g, b = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i]
    return int(r * 255), int(g * 255), int(b * 255)


class Rainbow:
    name = "rainbow"
    def draw(self, d, W, H, leds, t):
        rows = 30
        rh = H // rows
        for r in range(rows):
            h = ((t / 4000.0) + r / rows) % 1.0
            d.set_pen(d.create_pen(*_hsv_rgb(h, 1.0, 1.0)))
            d.rectangle(0, r * rh, W, rh + 1)
        leds.columns([_hsv_rgb(((t / 4000.0) + i / 7) % 1.0, 1.0, 1.0) for i in range(7)])


class Pulse:
    name = "pulse"
    color = (0xff, 0x66, 0x33)
    def draw(self, d, W, H, leds, t):
        phase = (math.sin(t / 800.0) + 1) / 2
        r, g, b = self.color
        scaled = (int(r * phase), int(g * phase), int(b * phase))
        d.set_pen(d.create_pen(*scaled))
        d.clear()
        leds.solid(scaled)


class Fire:
    name = "fire"
    def __init__(self):
        self._buf = None
    def draw(self, d, W, H, leds, t):
        cols = 7
        cw = W // cols
        cols_rgb = []
        for i in range(cols):
            n = (math.sin((t + i * 350) / 600.0) + 1) / 2
            r = int(255 * (0.6 + 0.4 * n))
            g = int(80 * n)
            b = int(20 * n * 0.5)
            cols_rgb.append((r, g, b))
            d.set_pen(d.create_pen(r, g, b))
            d.rectangle(i * cw, 0, cw + 1, H)
        leds.columns(cols_rgb)


class Wave:
    name = "wave"
    def draw(self, d, W, H, leds, t):
        d.set_pen(d.create_pen(8, 12, 24))
        d.clear()
        cols = []
        for i in range(7):
            x_center = int((math.sin((t + i * 400) / 700.0) + 1) / 2 * W)
            hue = (0.55 + 0.1 * math.sin(t / 2000.0 + i)) % 1.0
            r, g, b = _hsv_rgb(hue, 0.9, 1.0)
            d.set_pen(d.create_pen(r, g, b))
            d.circle(x_center, H // 2, 30 + int(20 * math.sin(t / 500.0 + i)))
            cols.append((r // 2, g // 2, b // 2))
        leds.columns(cols)


ANIMATIONS = [Rainbow(), Pulse(), Fire(), Wave()]
