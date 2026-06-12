import time

from app.screens.base import Screen
from app import theme
from app.net import dgx as net_dgx


class DGXScreen(Screen):
    name = "dgx"
    accent = theme.ACCENTS["dgx"]
    sources = ("dgx",)

    def __init__(self, ctx):
        super().__init__(ctx)
        self._pens = None
        self._detail = None            # container id when drilled into the detail view
        self._detail_data = None
        self._detail_err = None
        self._dscroll = 0
        self._container_rows = []      # [(y_top, id)] recorded during draw for hit-testing

    def leave(self):
        self._detail = None
        self._dscroll = 0

    def on_pad(self, key):
        if self._detail is not None:
            if key == "U":
                self._dscroll = max(0, self._dscroll - 1)
            elif key == "D":
                self._dscroll += 1

    def on_touch(self, x, y):
        if self._detail is not None:
            self._detail = None        # tap anywhere returns to the dashboard
            return
        for (ry, cid) in self._container_rows:
            if cid and ry <= y < ry + 30:
                self._open_detail(cid)
                return

    def _open_detail(self, cid):
        self._detail = cid
        self._detail_err = None
        self._detail_data = None
        self._dscroll = 0
        cfg = self.ctx.secrets.get("dgx") or {}
        url = cfg.get("url")
        if not url:
            self._detail_err = "no url"
            return
        data, err = net_dgx.container(url, cid)
        if err:
            self._detail_err = err
        else:
            self._detail_data = data

    def _ensure_pens(self):
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
            "warn": d.create_pen(*theme.WARN_AMBER),
            "err": d.create_pen(*theme.ERR_RED),
        }

    def _temp_color(self, c):
        if c is None:
            return self._pens["dim"]
        if c < 60:
            return self._pens["ok"]
        if c < 80:
            return self._pens["warn"]
        return self._pens["err"]

    def _bar(self, x, y, w, h, frac, fg):
        d = self.ctx.display
        d.set_pen(self._pens["panel_hi"])
        d.rectangle(x, y, w, h)
        if frac and frac > 0:
            d.set_pen(fg)
            d.rectangle(x, y, max(2, int(w * min(1.0, frac))), h)

    def draw(self):
        self._ensure_pens()
        if self._detail is not None:
            return self._draw_detail()
        d = self.ctx.display
        W, H = self.ctx.W, self.ctx.H
        s = self.ctx.state

        d.set_pen(self._pens["bg"])
        d.clear()

        d.set_pen(self._pens["accent"])
        d.text("DGX SPARK", 16, 14, W, 3)
        d.set_pen(self._pens["dim"])
        host = (s.dgx or {}).get("host") or "-"
        age = (int(time.time() - s.dgx_ts) if s.dgx_ts else None)
        age_s = "{}s ago".format(age) if age is not None else "no data"
        d.text("{}  -  {}".format(host, age_s), 16, 48, W, 2)

        if s.dgx_err and not s.dgx:
            d.set_pen(self._pens["err"])
            d.text("error: " + s.dgx_err, 16, 80, W - 32, 2)
            return

        data = s.dgx or {}
        gpus = data.get("gpu") or []
        y = 80
        for g in gpus[:2]:
            d.set_pen(self._pens["panel"])
            d.rectangle(12, y, W - 24, 110)
            d.set_pen(self._pens["text"])
            d.text(g.get("name") or "GPU", 24, y + 10, W - 48, 2)
            tc = g.get("temp_c")
            d.set_pen(self._temp_color(tc))
            d.text("{}C".format(tc if tc is not None else "-"), W - 110, y + 10, 100, 3)
            util = g.get("util_pct") or 0
            used = g.get("mem_used_mb")
            tot = g.get("mem_total_mb")
            self._bar(24, y + 55, W - 240, 16, util / 100.0, self._pens["accent"])
            d.set_pen(self._pens["dim"])
            d.text("util {}%".format(util), 24, y + 75, 200, 2)
            if tot:
                self._bar(24, y + 92, W - 240, 8, (used or 0) / tot, self._pens["warn"])
                d.set_pen(self._pens["dim"])
                d.text("vram {}/{}G".format((used or 0) // 1024, tot // 1024), 24, y + 102, 200, 1)
            else:
                d.set_pen(self._pens["dim"])
                d.text("unified memory -> see MEM", 24, y + 100, 300, 1)
            d.text("{}W".format(int(g.get("power_w") or 0)), W - 110, y + 75, 100, 2)
            y += 120

        cpu = (data.get("cpu") or {}).get("util_pct") or 0
        mem = (data.get("mem") or {}).get("pct") or 0
        net = data.get("net") or {}
        rx = (net.get("rx_bps") or 0) / 1_000_000
        tx = (net.get("tx_bps") or 0) / 1_000_000
        ph = 84
        d.set_pen(self._pens["panel"])
        d.rectangle(12, y, W - 24, ph)
        bx = 74
        bw = W - 24 - bx - 60
        d.set_pen(self._pens["dim"])
        d.text("CPU", 24, y + 8, 60, 2)
        self._bar(bx, y + 9, bw, 14, cpu / 100.0, self._pens["accent"])
        d.set_pen(self._pens["text"])
        d.text("{:.0f}%".format(cpu), W - 64, y + 8, 56, 2)
        d.set_pen(self._pens["dim"])
        d.text("MEM", 24, y + 32, 60, 2)
        self._bar(bx, y + 33, bw, 14, mem / 100.0, self._pens["warn"])
        d.set_pen(self._pens["text"])
        d.text("{:.0f}%".format(mem), W - 64, y + 32, 56, 2)
        d.set_pen(self._pens["dim"])
        d.text("net  rx {:.1f}  /  tx {:.1f}  Mb/s".format(rx, tx), 24, y + 58, W, 2)
        y += ph + 10

        d.set_pen(self._pens["text"])
        d.text("CONTAINERS", 16, y, W, 2)
        y += 22
        containers = data.get("containers") or []
        models_by_container = {}
        for m in data.get("models") or []:
            key = m.get("source") or "container"
            models_by_container[key] = m.get("model") or models_by_container.get(key)
        line_h = 30
        max_rows = max(0, (H - y - 30) // line_h)
        self._container_rows = []
        for c in containers[:max_rows]:
            color = self._pens["ok"] if c.get("status") == "running" else self._pens["dim"]
            d.set_pen(color)
            d.circle(22, y + 8, 4)
            d.set_pen(self._pens["text"])
            d.text(theme.ascii_only(c.get("name") or "?")[:26], 34, y, W - 40, 2)
            d.set_pen(self._pens["dim"])
            d.text(theme.ascii_only(c.get("image") or "")[:46], 34, y + 16, W - 40, 1)
            self._container_rows.append((y, c.get("id")))
            y += line_h

        models = data.get("models") or []
        tok_s_total = sum((m.get("tok_s") or 0) for m in models)
        pp_s_total = sum((m.get("pp_tok_s") or 0) for m in models)
        if tok_s_total or pp_s_total:
            d.set_pen(self._pens["accent"])
            d.text("{:.1f} tok/s  -  PP {:.1f}".format(tok_s_total, pp_s_total), 16, H - 28, W, 2)
        else:
            d.set_pen(self._pens["dim"])
            d.text("no tok/s source", 16, H - 28, W, 2)

    def _draw_detail(self):
        d = self.ctx.display
        W, H = self.ctx.W, self.ctx.H
        dd = self._detail_data or {}

        d.set_pen(self._pens["bg"])
        d.clear()
        d.set_pen(self._pens["accent"])
        nm = theme.ascii_only(dd.get("name") or self._detail or "?")
        d.text(nm[:18], 16, 14, W - 80, 3)
        d.set_pen(self._pens["dim"])
        d.text("< tap", W - 78, 22, 78, 2)

        if self._detail_err or dd.get("error"):
            d.set_pen(self._pens["err"])
            d.text("detail error:", 16, 58, W, 2)
            d.text(str(self._detail_err or dd.get("error"))[:56], 16, 82, W - 32, 1)
            return

        d.set_pen(self._pens["dim"])
        d.text(theme.ascii_only(dd.get("image") or "")[:52], 16, 46, W, 1)

        status = dd.get("status") or "?"
        if status == "running":
            st_pen = self._pens["ok"]
        elif status in ("exited", "dead", "restarting"):
            st_pen = self._pens["err"]
        else:
            st_pen = self._pens["warn"]
        d.set_pen(st_pen)
        d.text(status.upper(), 16, 64, 180, 2)
        d.set_pen(self._pens["dim"])
        meta = "restarts {}".format(dd.get("restart_count") if dd.get("restart_count") is not None else "-")
        if dd.get("exit_code") is not None:
            meta += "  exit {}".format(dd.get("exit_code"))
        if dd.get("health"):
            meta += "  {}".format(dd.get("health"))
        if dd.get("oom_killed"):
            meta += "  OOM!"
        d.text(meta, 130, 68, W - 140, 1)

        y = 90
        errors = dd.get("errors") or []
        if errors:
            d.set_pen(self._pens["err"])
            d.text("RECENT ERRORS", 16, y, W, 2)
            y += 22
            for ln in errors[-4:]:
                d.set_pen(self._pens["err"])
                d.text(theme.ascii_only(ln)[:66], 16, y, W - 24, 1)
                y += 16
            y += 6

        d.set_pen(self._pens["text"])
        d.text("LOG", 16, y, W, 2)
        y += 22
        recent = dd.get("recent") or []
        line_h = 16
        max_rows = max(1, (H - y - 24) // line_h)
        if self._dscroll > max(0, len(recent) - max_rows):
            self._dscroll = max(0, len(recent) - max_rows)
        view = recent[self._dscroll:self._dscroll + max_rows]
        d.set_pen(self._pens["dim"])
        for ln in view:
            d.text(theme.ascii_only(ln)[:68], 16, y, W - 24, 1)
            y += line_h

        if len(recent) > max_rows:
            d.set_pen(self._pens["dim"])
            d.text("U/D {}-{}/{}".format(self._dscroll + 1, self._dscroll + len(view), len(recent)),
                   W - 150, H - 16, 150, 1)
