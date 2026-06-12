import math

from app.screens.base import Screen
from app.hw.sensors import Sensors
from app import theme


class AltitudeScreen(Screen):
    name = "altitude"
    accent = theme.ACCENTS["altitude"]

    def __init__(self, ctx):
        super().__init__(ctx)
        self._pens = None
        self._vector = None
        self._ground_p = None
        self._last_alt = None
        self._last_alt_t = 0
        self._vspeed = 0.0
        self._smooth_xy = (0.0, 0.0)

    def enter(self):
        s = self.ctx.state.sensors
        if s.get("pressure_hpa"):
            self._ground_p = s["pressure_hpa"]

    def on_pad(self, key):
        if key == "A":
            self.enter()  # recalibrate ground

    def on_touch(self, x, y):
        if y > self.ctx.H - 60:
            self.enter()

    def _ensure(self):
        if self._pens is not None:
            return
        d = self.ctx.display
        self._pens = {
            "sky": d.create_pen(86, 159, 201),
            "ground": d.create_pen(101, 81, 63),
            "horizon": d.create_pen(255, 255, 255),
            "text": d.create_pen(*theme.TEXT),
            "dim": d.create_pen(*theme.TEXT_DIM),
            "accent": d.create_pen(*self.accent),
            "ring": d.create_pen(42, 52, 57),
            "craft": d.create_pen(220, 50, 40),
            "bg": d.create_pen(*theme.BG),
        }
        try:
            from picovector import ANTIALIAS_FAST, PicoVector, Polygon, Transform
            self._PV = PicoVector
            self._PO = Polygon
            self._TR = Transform
            self._AAF = ANTIALIAS_FAST
            self._vector = PicoVector(d)
            self._vector.set_antialiasing(ANTIALIAS_FAST)
        except ImportError:
            self._vector = None

    def draw(self):
        self._ensure()
        d = self.ctx.display
        W, H = self.ctx.W, self.ctx.H
        s = self.ctx.state.sensors

        ax = s.get("ax") or 0.0
        ay = s.get("ay") or 0.0
        az = s.get("az") or 0.0
        try:
            pitch, roll = Sensors.pitch_roll(ax, ay, az)
        except Exception:
            pitch = roll = 0.0
        px = pitch * 180 / math.pi
        rr = roll * 180 / math.pi

        sx, sy = self._smooth_xy
        a = 0.15
        sx = a * rr + (1 - a) * sx
        sy = a * px + (1 - a) * sy
        self._smooth_xy = (sx, sy)

        cx, cy = W // 2, H // 2
        if self._vector:
            self._vector.set_transform(self._TR())
            d.set_pen(self._pens["sky"])
            d.clear()
            t = self._TR()
            t.rotate(-sx, (cx, cy))
            t.translate(0, sy * 2)
            self._vector.set_transform(t)
            d.set_pen(self._pens["ground"])
            self._vector.draw(self._PO().rectangle(0, cy, W, H))
            d.set_pen(self._pens["horizon"])
            self._vector.draw(self._PO().rectangle(0, cy - 1, W, 2))
            for line in range(1, 6):
                w = 60 if line % 2 == 0 else 24
                self._vector.draw(self._PO().rectangle(cx - w // 2, cy - line * 16, w, 2))
                self._vector.draw(self._PO().rectangle(cx - w // 2, cy + line * 16, w, 2))
            self._vector.set_transform(self._TR())
            d.set_pen(self._pens["ring"])
            self._vector.draw(self._PO().circle(cx, cy, 195, stroke=8))
            d.set_pen(self._pens["craft"])
            self._vector.draw(self._PO().rectangle(cx - 70, cy - 1, 50, 3, (2, 2, 2, 2)))
            self._vector.draw(self._PO().rectangle(cx + 20, cy - 1, 50, 3, (2, 2, 2, 2)))
            self._vector.draw(self._PO().circle(cx, cy, 4))
        else:
            d.set_pen(self._pens["sky"])
            d.clear()
            d.set_pen(self._pens["ground"])
            d.rectangle(0, cy + int(sy * 2), W, H - cy)
            d.set_pen(self._pens["horizon"])
            d.line(0, cy + int(sy * 2), W, cy + int(sy * 2))

        d.set_pen(self._pens["accent"])
        d.text("ALTITUDE", 16, 14, W, 2)

        sea = (self.ctx.secrets.get("altitude", {}) or {}).get("sea_level_hpa", 1013.25)
        cur_p = s.get("pressure_hpa")
        alt_abs = Sensors.altitude_m(cur_p, sea) if cur_p else None
        alt_rel = None
        if cur_p and self._ground_p:
            alt_rel = Sensors.altitude_m(cur_p, self._ground_p)

        import time
        now = time.ticks_ms()
        if alt_abs is not None and self._last_alt is not None:
            dt = max(0.01, time.ticks_diff(now, self._last_alt_t) / 1000.0)
            self._vspeed = 0.7 * self._vspeed + 0.3 * (alt_abs - self._last_alt) / dt
        if alt_abs is not None:
            self._last_alt = alt_abs
            self._last_alt_t = now

        d.set_pen(self._pens["text"])
        d.text("{:>6} m MSL".format("{:.0f}".format(alt_abs) if alt_abs else "-"),
               W - 200, 14, 200, 3)
        d.text("{:+.1f} m AGL".format(alt_rel) if alt_rel is not None else "AGL -",
               W - 200, 50, 200, 2)
        d.set_pen(self._pens["dim"])
        d.text("{:+.1f} m/s".format(self._vspeed), W - 200, 78, 200, 2)
        d.text("p {:.1f} hPa".format(cur_p) if cur_p else "p -", 16, H - 24, W, 2)
        d.text("A or tap-bottom: zero AGL", 16, H - 48, W, 1)
