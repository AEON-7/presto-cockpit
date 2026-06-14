import time

from app.screens.base import Screen
from app import theme


class SettingsScreen(Screen):
    name = "settings"
    accent = theme.ACCENTS["settings"]
    sources = ("dgx", "openclaw", "crypto")

    def __init__(self, ctx):
        super().__init__(ctx)
        self._pens = None
        self._rssi = None
        self._last_rssi_check = 0
        W = ctx.W
        # tappable control rects (x, y, w, h) — kept in sync with draw()
        self._btn_minus = (W - 156, 54, 44, 38)
        self._btn_plus = (W - 58, 54, 44, 38)
        self._btn_autodim = (W - 156, 104, 134, 30)

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
            "ok": d.create_pen(*theme.OK_GREEN),
            "err": d.create_pen(*theme.ERR_RED),
        }

    def _wifi_rssi(self):
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_rssi_check) < 2000:
            return self._rssi
        self._last_rssi_check = now
        try:
            import network
            wlan = network.WLAN(network.STA_IF)
            self._rssi = wlan.status("rssi") if wlan.isconnected() else None
        except Exception:
            self._rssi = None
        return self._rssi

    @staticmethod
    def _hit(rect, x, y):
        rx, ry, rw, rh = rect
        return rx <= x <= rx + rw and ry <= y <= ry + rh

    def on_touch(self, x, y):
        app = getattr(self.ctx, "app", None)
        if app is None:
            return
        if self._hit(self._btn_minus, x, y):
            app._adjust_brightness(-0.1)
        elif self._hit(self._btn_plus, x, y):
            app._adjust_brightness(0.1)
        elif self._hit(self._btn_autodim, x, y):
            app.set_auto_dim(not self.ctx.state.auto_dim)

    def draw(self):
        self._ensure()
        d = self.ctx.display
        W, H = self.ctx.W, self.ctx.H
        s = self.ctx.state

        d.set_pen(self._pens["bg"])
        d.clear()
        d.set_pen(self._pens["accent"])
        d.text("SETTINGS", 16, 14, W, 3)

        # --- Brightness control ---
        d.set_pen(self._pens["panel"])
        d.rectangle(12, 48, W - 24, 50)
        d.set_pen(self._pens["text"])
        d.text("BRIGHTNESS", 24, 60, W, 2)
        d.set_pen(self._pens["accent"])
        d.text("{}%".format(int(round(s.brightness * 100))), 168, 56, 120, 3)
        for rect, glyph in ((self._btn_minus, "-"), (self._btn_plus, "+")):
            rx, ry, rw, rh = rect
            d.set_pen(self._pens["panel_hi"])
            d.rectangle(rx, ry, rw, rh)
            d.set_pen(self._pens["text"])
            d.text(glyph, rx + (16 if glyph == "-" else 14), ry + 6, rw, 3)

        # --- Auto-dim toggle ---
        d.set_pen(self._pens["dim"])
        d.text("AUTO-DIM (light sensor)", 24, 110, W, 2)
        rx, ry, rw, rh = self._btn_autodim
        on = s.auto_dim
        d.set_pen(self._pens["ok"] if on else self._pens["panel_hi"])
        d.rectangle(rx, ry, rw, rh)
        d.set_pen(self._pens["bg"] if on else self._pens["text"])
        d.text("ON" if on else "OFF", rx + 50, ry + 7, rw, 2)

        # --- Service / link status ---
        rows = []
        rows.append(("wifi", "connected" if s.wifi_connected else "down", s.wifi_connected))
        rssi = self._wifi_rssi()
        if rssi is not None:
            rows.append(("  rssi", "{} dBm".format(rssi), True))
        rows.append(("ntp", "synced" if s.time_synced else "not synced", s.time_synced))

        def reach(ts, max_age):
            return s.fresh(ts, max_age)

        rows.append(("dgx",
                     "ok ({}s)".format(int(time.time() - s.dgx_ts)) if reach(s.dgx_ts, 10) else (s.dgx_err or "stale"),
                     reach(s.dgx_ts, 10)))
        rows.append(("openclaw",
                     "ok ({}s)".format(int(time.time() - s.openclaw_ts)) if reach(s.openclaw_ts, 15) else (s.openclaw_err or "stale"),
                     reach(s.openclaw_ts, 15)))
        rows.append(("kuma",
                     "ok ({}s)".format(int(time.time() - s.kuma_ts)) if reach(s.kuma_ts, 60) else (s.kuma_err or "off"),
                     reach(s.kuma_ts, 60)))
        rows.append(("sensors", "ok" if s.sensors_ok else "missing", s.sensors_ok))

        y = 150
        for label, value, ok in rows:
            d.set_pen(self._pens["panel"])
            d.rectangle(12, y, W - 24, 32)
            d.set_pen(self._pens["text"])
            d.text(label, 24, y + 6, W, 2)
            d.set_pen(self._pens["ok"] if ok else self._pens["err"])
            d.circle(W - 36, y + 16, 6)
            d.set_pen(self._pens["dim"])
            d.text(str(value)[:30], 140, y + 6, W - 200, 2)
            y += 37

        d.set_pen(self._pens["dim"])
        d.text("tap +/- or use the pad +/- keys to set brightness", 16, H - 22, W, 1)
