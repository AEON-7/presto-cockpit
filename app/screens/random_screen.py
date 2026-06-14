import time

from app.screens.base import Screen
from app import theme

MODES = ["COIN", "D6", "D20", "2D6"]


class RandomScreen(Screen):
    """Coin flip + dice roll, with every result drawn from the EntropyPool that the
    app continuously stirs from raw sensor noise (IMU + barometer + light) plus the
    exact microsecond of each tap. True-ish random, physically sourced."""

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

    def _ensure(self):
        if self._pens is not None:
            return
        d = self.ctx.display
        self._pens = {
            "bg": d.create_pen(*theme.BG),
            "panel": d.create_pen(*theme.PANEL),
            "text": d.create_pen(*theme.TEXT),
            "dim": d.create_pen(*theme.TEXT_DIM),
            "accent": d.create_pen(*self.accent),
            "warn": d.create_pen(*theme.WARN_AMBER),
            "die": d.create_pen(0xea, 0xec, 0xf2),
        }
        W = self.ctx.W
        cw = (W - 24) // 4
        self._chips = [(12 + i * cw, 70, cw - 6, 36) for i in range(4)]

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

    def _roll(self):
        rng = self._rng()
        if rng is None:
            return
        try:                            # fold the tap's exact microsecond (human jitter) in
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

    # ---- draw ------------------------------------------------------------
    def draw(self):
        self._ensure()
        d = self.ctx.display
        W, H = self.ctx.W, self.ctx.H
        p = self._pens
        rng = self._rng()

        d.set_pen(p["bg"])
        d.clear()
        d.set_pen(p["accent"])
        d.text("RANDOM", 16, 14, W, 3)
        d.set_pen(p["dim"])
        d.text("true random from live sensor noise", 16, 48, W, 1)

        self._draw_chips(d, p)

        animating = time.ticks_diff(self._anim_until, time.ticks_ms()) > 0
        self._draw_result(d, p, rng, animating)
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
        cy = 238
        R = 90
        mode = MODES[self._mode]

        if rng is None or not rng.ready():
            self._ctext(d, "gathering", 3, cx, cy - 28, p["dim"])
            self._ctext(d, "sensor entropy...", 2, cx, cy + 12, p["dim"])
            return

        if self._result is None and not animating:
            self._ctext(d, "TAP TO " + ("FLIP" if mode == "COIN" else "ROLL"),
                        3, cx, cy - 12, p["accent"])
            return

        if mode == "COIN":
            v = ("H" if rng.bits(1) == 0 else "T") if animating else self._result
            d.set_pen(p["accent"])
            d.circle(cx, cy, R)
            self._ctext_mid(d, v, 9, cx, cy, p["bg"])
            if not animating:
                self._ctext(d, "HEADS" if v == "H" else "TAILS", 3, cx, cy + R + 8, p["accent"])
        elif mode == "D6":
            v = (rng.randbelow(6) + 1) if animating else self._result
            self._die_face(d, p, v, cx - 90, cy - 90, 180)
        elif mode == "D20":
            v = (rng.randbelow(20) + 1) if animating else self._result
            d.set_pen(p["accent"])
            d.circle(cx, cy, R)
            self._ctext_mid(d, str(v), 9, cx, cy, p["bg"])
            if not animating:
                self._ctext(d, "d20", 2, cx, cy + R + 10, p["accent"])
        elif mode == "2D6":
            if animating:
                a, b = rng.randbelow(6) + 1, rng.randbelow(6) + 1
            else:
                a, b = self._result
            s = 132
            self._die_face(d, p, a, cx - s - 8, cy - s // 2, s)
            self._die_face(d, p, b, cx + 8, cy - s // 2, s)
            if not animating:
                self._ctext(d, "= {}".format(a + b), 4, cx, cy + s // 2 + 14, p["accent"])

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

    def _draw_footer(self, d, p, rng):
        W, H = self.ctx.W, self.ctx.H
        cx = W // 2
        mode = MODES[self._mode]
        if mode == "COIN":
            c = self._counts.get("COIN", {"H": 0, "T": 0})
            txt = "H {}   T {}   ({} flips)".format(c["H"], c["T"], c["H"] + c["T"])
        else:
            h = self._counts.get(mode, [])
            txt = "last:  " + ("  ".join(str(x) for x in h) if h else "-")
        self._ctext(d, txt, 2, cx, H - 92, p["dim"])

        bx, bw, by = 16, W - 32, H - 44
        d.set_pen(p["panel"])
        d.rectangle(bx, by, bw, 12)
        f = rng.fill() if rng else 0.0
        ready = bool(rng and rng.ready())
        d.set_pen(p["accent"] if ready else p["warn"])
        d.rectangle(bx, by, int(bw * f), 12)
        d.set_pen(p["dim"])
        src = rng.sources if rng else "-"
        d.text("entropy: {} - {}".format("ARMED" if ready else "warming up", src), bx, H - 28, W, 1)
        d.text("tap to roll  -  tap a mode to switch", bx, H - 16, W, 1)
