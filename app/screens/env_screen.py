from app.screens.base import Screen
from app import theme


class EnvScreen(Screen):
    name = "env"
    accent = theme.ACCENTS["env"]

    HISTORY_LEN = 90  # ~9s at 100ms sensor poll

    def __init__(self, ctx):
        super().__init__(ctx)
        self._pens = None
        self._hist = {"temp_c": [], "humidity": [], "pressure_hpa": [], "lux": []}
        self._last = 0

    def _ensure_pens(self):
        if self._pens is not None:
            return
        d = self.ctx.display
        self._pens = {
            "bg": d.create_pen(*theme.BG),
            "panel": d.create_pen(*theme.PANEL),
            "text": d.create_pen(*theme.TEXT),
            "dim": d.create_pen(*theme.TEXT_DIM),
            "accent": d.create_pen(*self.accent),
            "spark": d.create_pen(*theme.lerp(self.accent, theme.PANEL, 0.4)),
        }

    def _record(self):
        import time
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last) < 500:
            return
        self._last = now
        for k in self._hist:
            v = self.ctx.state.sensors.get(k)
            if v is None:
                continue
            buf = self._hist[k]
            buf.append(v)
            if len(buf) > self.HISTORY_LEN:
                del buf[0]

    def _spark(self, x, y, w, h, buf):
        if len(buf) < 2:
            return
        d = self.ctx.display
        lo = min(buf)
        hi = max(buf)
        rng = hi - lo or 1
        d.set_pen(self._pens["spark"])
        step = w / (len(buf) - 1)
        prev = None
        for i, v in enumerate(buf):
            px = int(x + i * step)
            py = int(y + h - ((v - lo) / rng) * h)
            if prev:
                d.line(prev[0], prev[1], px, py)
            prev = (px, py)

    def _tile(self, x, y, w, h, title, value, unit, hist_key):
        d = self.ctx.display
        d.set_pen(self._pens["panel"])
        d.rectangle(x, y, w, h)
        d.set_pen(self._pens["dim"])
        d.text(title, x + 12, y + 8, w, 2)
        d.set_pen(self._pens["text"])
        d.text(value, x + 12, y + 32, w, 5)
        d.set_pen(self._pens["dim"])
        d.text(unit, x + w - 60, y + 44, 60, 2)
        self._spark(x + 12, y + h - 38, w - 24, 28, self._hist[hist_key])

    def draw(self):
        self._ensure_pens()
        self._record()
        d = self.ctx.display
        W, H = self.ctx.W, self.ctx.H
        s = self.ctx.state.sensors

        d.set_pen(self._pens["bg"])
        d.clear()
        d.set_pen(self._pens["accent"])
        d.text("ENVIRONMENT", 16, 14, W, 3)
        if not self.ctx.state.sensors_ok:
            d.set_pen(self._pens["dim"])
            d.text("no multi-sensor stick detected", 16, 56, W, 2)
            return

        cell_w = (W - 30) // 2
        cell_h = (H - 100) // 2

        def fmt(v, kind):
            if v is None:
                return "-"
            if kind == "t":
                return "{:.1f}".format(v)
            if kind == "h":
                return "{:.0f}".format(v)
            if kind == "p":
                return "{:.0f}".format(v)
            if kind == "l":
                return "{:.0f}".format(v)
            return str(v)

        self._tile(12, 80, cell_w, cell_h, "TEMP", fmt(s.get("temp_c"), "t"), "C", "temp_c")
        self._tile(18 + cell_w, 80, cell_w, cell_h, "HUMIDITY", fmt(s.get("humidity"), "h"), "%", "humidity")
        self._tile(12, 86 + cell_h, cell_w, cell_h, "PRESSURE", fmt(s.get("pressure_hpa"), "p"), "hPa", "pressure_hpa")
        self._tile(18 + cell_w, 86 + cell_h, cell_w, cell_h, "LIGHT", fmt(s.get("lux"), "l"), "lux", "lux")

        prox = s.get("prox")
        if prox is not None:
            d.set_pen(self._pens["dim"])
            d.text("prox {}".format(int(prox)), 16, H - 24, W, 2)
