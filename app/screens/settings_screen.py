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

    def draw(self):
        self._ensure()
        d = self.ctx.display
        W, H = self.ctx.W, self.ctx.H
        s = self.ctx.state

        d.set_pen(self._pens["bg"])
        d.clear()
        d.set_pen(self._pens["accent"])
        d.text("SETTINGS", 16, 14, W, 3)

        rows = []
        rows.append(("wifi", "connected" if s.wifi_connected else "down",
                     s.wifi_connected))
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
        rows.append(("crypto",
                     "ok ({}s)".format(int(time.time() - s.crypto_ts)) if reach(s.crypto_ts, 90) else (s.crypto_err or "stale"),
                     reach(s.crypto_ts, 90)))
        rows.append(("sensors", "ok" if s.sensors_ok else "missing", s.sensors_ok))

        y = 60
        for label, value, ok in rows:
            d.set_pen(self._pens["panel"])
            d.rectangle(12, y, W - 24, 36)
            d.set_pen(self._pens["text"])
            d.text(label, 24, y + 8, W, 2)
            d.set_pen(self._pens["ok"] if ok else self._pens["err"])
            d.circle(W - 36, y + 18, 6)
            d.set_pen(self._pens["dim"])
            d.text(str(value)[:32], 140, y + 8, W - 200, 2)
            y += 42

        d.set_pen(self._pens["dim"])
        d.text("L/R: change screen  -  +/-: led brightness",
               16, H - 40, W, 1)
        d.text("edit /secrets.json over mpremote to change config",
               16, H - 22, W, 1)
