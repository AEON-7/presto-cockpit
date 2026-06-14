import time

from app.screens.base import Screen
from app import theme


class KumaScreen(Screen):
    name = "kuma"
    accent = theme.ACCENTS["kuma"]
    sources = ("kuma",)

    def __init__(self, ctx):
        super().__init__(ctx)
        self._pens = None
        self._scroll = 0

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
            "warn": d.create_pen(*theme.WARN_AMBER),
            "err": d.create_pen(*theme.ERR_RED),
        }

    def _up_pen(self, up):
        if up == 1:
            return self._pens["ok"]
        if up in (2, 3):           # pending / maintenance
            return self._pens["warn"]
        return self._pens["err"]   # 0 = down

    def on_pad(self, key):
        if key == "U":
            self._scroll = max(0, self._scroll - 1)
        elif key == "D":
            self._scroll += 1

    def draw(self):
        self._ensure()
        d = self.ctx.display
        W, H = self.ctx.W, self.ctx.H
        s = self.ctx.state
        p = self._pens

        d.set_pen(p["bg"])
        d.clear()
        d.set_pen(p["accent"])
        d.text("KUMA", 16, 14, W, 3)

        mons = s.kuma or []
        if not mons:
            if s.kuma_err:
                d.set_pen(p["err"])
                d.text("kuma: " + str(s.kuma_err)[:40], 16, 60, W - 24, 2)
                d.set_pen(p["dim"])
                d.text("set KUMA_URL + KUMA_API_KEY in secrets.json", 16, 92, W - 24, 1)
            else:
                d.set_pen(p["dim"])
                d.text("waiting for Uptime Kuma...", 16, 60, W, 2)
            return

        total = len(mons)
        up_n = 0
        for m in mons:
            if m["up"] == 1:
                up_n += 1
        down_n = total - up_n
        d.set_pen(p["ok"] if down_n == 0 else p["err"])
        sub = "ALL UP - {}/{}".format(up_n, total) if down_n == 0 \
            else "{} DOWN - {}/{} up".format(down_n, up_n, total)
        age = int(time.time() - s.kuma_ts) if s.kuma_ts else None
        if age is not None:
            sub += " - {}s".format(age)
        d.text(sub, 16, 48, W, 2)

        y = 80
        row_h = 40
        max_rows = max(1, (H - y - 24) // row_h)
        if self._scroll > max(0, total - max_rows):
            self._scroll = max(0, total - max_rows)
        for m in mons[self._scroll:self._scroll + max_rows]:
            d.set_pen(p["panel"])
            d.rectangle(12, y, W - 24, row_h - 6)
            d.set_pen(self._up_pen(m["up"]))
            d.circle(30, y + 17, 7)
            d.set_pen(p["text"])
            d.text(theme.ascii_only(m["name"])[:24], 48, y + 4, W - 200, 2)
            rt = m.get("response_ms")
            d.set_pen(p["dim"])
            d.text("{} ms".format(int(rt)) if rt is not None else "-", 48, y + 22, 130, 1)
            roll = s.kuma_roll.get(m["name"])
            if roll and roll[1]:
                rel = 100.0 * roll[0] / roll[1]
                d.set_pen(p["ok"] if rel >= 99 else (p["warn"] if rel >= 90 else p["err"]))
                d.text("{:.1f}%".format(rel), W - 98, y + 4, 92, 2)
                d.set_pen(p["dim"])
                d.text("uptime", W - 92, y + 24, 80, 1)
            y += row_h

        d.set_pen(p["dim"])
        d.text("reliability since boot", 16, H - 20, W, 1)
        if total > max_rows:
            d.text("U/D", W - 52, H - 20, 52, 1)
