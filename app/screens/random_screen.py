import time

from app.screens.base import Screen
from app import theme

MODES = ["COIN", "D6", "D20", "2D6"]

# Shake-to-roll: trigger on |accel| deviation from a slow gravity baseline.
# Calibrated on this device: rest deviation < 50, a hard shake reaches ~9700.
SHAKE_THRESHOLD = 2500.0
SHAKE_COOLDOWN_MS = 600

# Layout
RESULT_CY = 196
R_CIRCLE = 78
DIE_S = 162
TWO_S = 124
LABEL_Y = RESULT_CY + R_CIRCLE + 6
COUNTS_Y = 300
FEED_Y = 322
FEED_H = 30
HEX_Y = FEED_Y + FEED_H + 8
STATE_Y = 384
HINT_Y = 402


class RandomScreen(Screen):
    """Coin flip + dice roll, every result drawn from the EntropyPool the app stirs
    from raw sensor noise. Roll with the pad (A), a tap, or a physical shake. Two
    live "random data feed" animations (a scrolling bar stream + a hex stream) are
    pulled straight from the whitened pool so you can watch the randomness flow."""

    name = "random"
    accent = theme.ACCENTS["random"]
    sources = ()                       # no network; entropy comes from the sensor loop

    def __init__(self, ctx):
        super().__init__(ctx)
        self._pens = None
        self._chips = []
        self._mode = 0
        self._result = None
        self._anim_until = 0
        self._counts = {}              # "COIN" -> {"H","T"}; others -> recent list
        # shake detection
        self._g = None
        self._shake_last = 0
        # animated feeds
        self._bars = []
        self._hexs = ""
        self._nbars = 64
        self._nhex = 34

    def _ensure(self):
        if self._pens is not None:
            return
        d = self.ctx.display
        self._pens = {
            "bg": d.create_pen(*theme.BG),
            "panel": d.create_pen(*theme.PANEL),
            "panel_hi": d.create_pen(*theme.PANEL_HI),
            "text": d.create_pen(*theme.TEXT),
            "dim": d.create_pen(*theme.TEXT_DIM),
            "accent": d.create_pen(*self.accent),
            "warn": d.create_pen(*theme.WARN_AMBER),
            "die": d.create_pen(0xea, 0xec, 0xf2),
        }
        W = self.ctx.W
        cw = (W - 24) // 4
        self._chips = [(12 + i * cw, 70, cw - 6, 36) for i in range(4)]
        self._nbars = (W - 32) // 6
        self._nhex = (W - 36) // 12

    def _rng(self):
        return getattr(self.ctx, "rng", None)

    # ---- centered-text helpers -------------------------------------------
    def _ctext(self, d, s, scale, cx, y, pen):
        s = theme.ascii_only(s)
        try:
            w = d.measure_text(s, scale)
        except Exception:
            w = len(s) * 6 * scale
        d.set_pen(pen)
        d.text(s, int(cx - w // 2), int(y), self.ctx.W, scale)

    def _ctext_mid(self, d, s, scale, cx, cy, pen):
        self._ctext(d, s, scale, cx, cy - 4 * scale, pen)

    # ---- input -----------------------------------------------------------
    def on_touch(self, x, y):
        for i, (rx, ry, rw, rh) in enumerate(self._chips):
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                if i != self._mode:
                    self._mode = i
                    self._result = None
                    self._anim_until = 0
                return
        self._roll()

    def on_pad(self, key):
        # Works without the touchscreen: any action button rolls; U/D pick the mode.
        if key in ("A", "B", "X", "Y"):
            self._roll()
        elif key == "U":
            self._mode = (self._mode - 1) % len(MODES)
            self._result = None
            self._anim_until = 0
        elif key == "D":
            self._mode = (self._mode + 1) % len(MODES)
            self._result = None
            self._anim_until = 0

    def _roll(self):
        rng = self._rng()
        if rng is None:
            return
        try:                            # fold the trigger's exact microsecond (human jitter) in
            rng.stir(self.ctx.state.sensors)
        except Exception:
            pass
        if not rng.ready():
            return
        m = MODES[self._mode]
        if m == "COIN":
            self._result = "H" if rng.bits(1) == 0 else "T"
            c = self._counts.setdefault("COIN", {"H": 0, "T": 0})
            c[self._result] += 1
        elif m == "D6":
            self._result = rng.randbelow(6) + 1
            self._push("D6", self._result)
        elif m == "D20":
            self._result = rng.randbelow(20) + 1
            self._push("D20", self._result)
        elif m == "2D6":
            a = rng.randbelow(6) + 1
            b = rng.randbelow(6) + 1
            self._result = (a, b)
            self._push("2D6", a + b)
        self._anim_until = time.ticks_add(time.ticks_ms(), 520)

    def _push(self, mode, val):
        h = self._counts.setdefault(mode, [])
        h.append(val)
        if len(h) > 8:
            del h[0]

    # ---- per-frame update: shake detection + feed the animated streams ----
    def _update(self, rng):
        s = self.ctx.state.sensors
        ax, ay, az = s.get("ax"), s.get("ay"), s.get("az")
        if ax is not None and ay is not None and az is not None:
            mag = (ax * ax + ay * ay + az * az) ** 0.5
            if self._g is None:
                self._g = mag
            dev = mag - self._g
            if dev < 0:
                dev = -dev
            self._g += (mag - self._g) * 0.05         # slow gravity tracking
            now = time.ticks_ms()
            if (dev > SHAKE_THRESHOLD and rng is not None and rng.ready()
                    and time.ticks_diff(self._anim_until, now) <= 0
                    and time.ticks_diff(now, self._shake_last) > SHAKE_COOLDOWN_MS):
                self._shake_last = now
                self._roll()
        if rng is not None and rng.ready():
            self._bars.append(rng.bits(8) / 255.0)
            if len(self._bars) > self._nbars:
                del self._bars[0]
            self._hexs = (self._hexs + "0123456789ABCDEF"[rng.bits(4)])[-self._nhex:]

    # ---- draw ------------------------------------------------------------
    def draw(self):
        self._ensure()
        d = self.ctx.display
        W, H = self.ctx.W, self.ctx.H
        p = self._pens
        rng = self._rng()
        self._update(rng)

        d.set_pen(p["bg"])
        d.clear()
        d.set_pen(p["accent"])
        d.text("RANDOM", 16, 12, W, 3)
        d.set_pen(p["dim"])
        d.text("true random from live sensor noise", 16, 44, W, 1)

        self._draw_chips(d, p)
        animating = time.ticks_diff(self._anim_until, time.ticks_ms()) > 0
        self._draw_result(d, p, rng, animating)
        self._draw_feeds(d, p, rng)
        self._draw_footer(d, p, rng)

    def _draw_chips(self, d, p):
        for i, (rx, ry, rw, rh) in enumerate(self._chips):
            active = (i == self._mode)
            d.set_pen(p["accent"] if active else p["panel"])
            d.rectangle(rx, ry, rw, rh)
            self._ctext(d, MODES[i], 2, rx + rw // 2, ry + rh // 2 - 8,
                        p["bg"] if active else p["dim"])

    def _draw_result(self, d, p, rng, animating):
        cx = self.ctx.W // 2
        cy = RESULT_CY
        mode = MODES[self._mode]

        if rng is None or not rng.ready():
            self._ctext(d, "gathering", 3, cx, cy - 28, p["dim"])
            self._ctext(d, "sensor entropy...", 2, cx, cy + 12, p["dim"])
            return

        if self._result is None and not animating:
            self._ctext(d, "PRESS A OR SHAKE", 3, cx, cy - 26, p["accent"])
            self._ctext(d, "TO " + ("FLIP" if mode == "COIN" else "ROLL"), 2, cx, cy + 12, p["dim"])
            return

        if mode == "COIN":
            v = ("H" if rng.bits(1) == 0 else "T") if animating else self._result
            d.set_pen(p["accent"])
            d.circle(cx, cy, R_CIRCLE)
            self._ctext_mid(d, v, 9, cx, cy, p["bg"])
            if not animating:
                self._ctext(d, "HEADS" if v == "H" else "TAILS", 2, cx, LABEL_Y, p["accent"])
        elif mode == "D6":
            v = (rng.randbelow(6) + 1) if animating else self._result
            self._die_face(d, p, v, cx - DIE_S // 2, cy - DIE_S // 2, DIE_S)
        elif mode == "D20":
            v = (rng.randbelow(20) + 1) if animating else self._result
            d.set_pen(p["accent"])
            d.circle(cx, cy, R_CIRCLE)
            self._ctext_mid(d, str(v), 9, cx, cy, p["bg"])
            if not animating:
                self._ctext(d, "d20", 2, cx, LABEL_Y, p["accent"])
        elif mode == "2D6":
            if animating:
                a, b = rng.randbelow(6) + 1, rng.randbelow(6) + 1
            else:
                a, b = self._result
            self._die_face(d, p, a, cx - TWO_S - 8, cy - TWO_S // 2, TWO_S)
            self._die_face(d, p, b, cx + 8, cy - TWO_S // 2, TWO_S)
            if not animating:
                self._ctext(d, "= {}".format(a + b), 2, cx, LABEL_Y, p["accent"])

    def _die_face(self, d, p, n, fx, fy, s):
        d.set_pen(p["accent"])                       # colored border
        d.rectangle(int(fx - 4), int(fy - 4), int(s + 8), int(s + 8))
        d.set_pen(p["die"])
        d.rectangle(int(fx), int(fy), int(s), int(s))
        r = max(6, s // 12)
        x1, x2, x3 = fx + s * 0.26, fx + s * 0.5, fx + s * 0.74
        y1, y2, y3 = fy + s * 0.26, fy + s * 0.5, fy + s * 0.74
        layout = {
            1: [(x2, y2)],
            2: [(x1, y1), (x3, y3)],
            3: [(x1, y1), (x2, y2), (x3, y3)],
            4: [(x1, y1), (x3, y1), (x1, y3), (x3, y3)],
            5: [(x1, y1), (x3, y1), (x2, y2), (x1, y3), (x3, y3)],
            6: [(x1, y1), (x3, y1), (x1, y2), (x3, y2), (x1, y3), (x3, y3)],
        }.get(n, [])
        d.set_pen(p["bg"])
        for px, py in layout:
            d.circle(int(px), int(py), int(r))

    def _draw_feeds(self, d, p, rng):
        # Two live views of the whitened entropy stream, redrawn every frame.
        W = self.ctx.W
        ready = bool(rng and rng.ready())
        d.set_pen(p["panel"])
        d.rectangle(16, FEED_Y, W - 32, FEED_H)
        d.set_pen(p["accent"] if ready else p["dim"])
        for i, v in enumerate(self._bars):           # scrolling random-bar stream
            h = int(FEED_H * v)
            if h < 1:
                h = 1
            d.rectangle(16 + i * 6, FEED_Y + (FEED_H - h), 5, h)
        d.set_pen(p["dim"])                           # scrolling hex stream
        d.text(self._hexs, 16, HEX_Y, W, 2)

    def _draw_footer(self, d, p, rng):
        W = self.ctx.W
        cx = W // 2
        mode = MODES[self._mode]
        if mode == "COIN":
            c = self._counts.get("COIN", {"H": 0, "T": 0})
            txt = "H %d   T %d   (%d flips)" % (c["H"], c["T"], c["H"] + c["T"])
        else:
            h = self._counts.get(mode, [])
            txt = "last:  " + ("  ".join(str(x) for x in h) if h else "-")
        self._ctext(d, txt, 2, cx, COUNTS_Y, p["dim"])

        ready = bool(rng and rng.ready())
        src = rng.sources if rng else "-"
        d.set_pen(p["dim"])
        d.text("entropy: %s - %s" % ("ARMED" if ready else "warming up", src), 16, STATE_Y, W, 1)
        d.text("A = roll/flip    U/D = mode    or shake it", 16, HINT_Y, W, 1)
