from app.screens.base import Screen
from app import theme


def _gb(mb):
    return (mb or 0) / 1024.0


def _short(mb):
    mb = mb or 0
    if mb >= 1024:
        return "{:.1f}G".format(mb / 1024.0)
    return "{:.0f}M".format(mb)


KIND_RGB = {
    "gateway": theme.ACCENTS["openclaw"],   # all chat, shared
    "voip": (0x4d, 0xc9, 0xb0),             # per-agent voice process
    "browser": (0x9b, 0x6d, 0xff),          # shared headless browser
    "run": theme.WARN_AMBER,                # spawned run / subagent
    "other": theme.TEXT_DIM,
}


class ResourcesScreen(Screen):
    """Box-level resource view for the OpenClaw gateway host: CPU + RAM donuts
    and a ranked list of the heaviest processes (gateway=all chat shared, each
    voip agent, subagents, browser) so you can see who to halt."""
    name = "resources"
    accent = theme.ACCENTS["resources"]
    sources = ("openclaw",)

    def __init__(self, ctx):
        super().__init__(ctx)
        self._pens = None
        self._scroll = 0

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
            "track": d.create_pen(0x2a, 0x30, 0x3c),
            "ok": d.create_pen(*theme.OK_GREEN),
            "amber": d.create_pen(*theme.WARN_AMBER),
            "err": d.create_pen(*theme.ERR_RED),
        }
        self._kind_pens = {k: d.create_pen(*v) for k, v in KIND_RGB.items()}

    def on_pad(self, key):
        if key == "U":
            self._scroll = max(0, self._scroll - 1)
        elif key == "D":
            self._scroll += 1

    def _ctext(self, s, cx, y, scale, pen):
        d = self.ctx.display
        w = d.measure_text(s, scale)
        d.set_pen(pen)
        d.text(s, int(cx - w / 2), y, self.ctx.W, scale)

    def _load_pen(self, pct):
        if pct < 0.6:
            return self._pens["ok"]
        if pct < 0.85:
            return self._pens["amber"]
        return self._pens["err"]

    def _gauge(self, cx, cy, r, pct, big, label, sub):
        d = self.ctx.display
        fill = self._load_pen(pct)
        theme.ring_gauge(d, cx, cy, r, pct, fill, self._pens["track"], dot_r=6)
        self._ctext(big, cx, cy - 16, 3, self._pens["text"])
        self._ctext(label, cx, cy + 16, 2, self._pens["dim"])
        if sub:
            self._ctext(sub, cx, cy + 38, 1, self._pens["dim"])

    def draw(self):
        self._ensure_pens()
        d = self.ctx.display
        W, H = self.ctx.W, self.ctx.H
        host = self.ctx.state.openclaw_host or {}

        d.set_pen(self._pens["bg"])
        d.clear()
        d.set_pen(self._pens["accent"])
        d.text("OPENCLAW BOX", 16, 12, W, 3)

        if not host:
            d.set_pen(self._pens["dim"])
            d.text("waiting for shim host stats...", 16, 60, W - 32, 2)
            return

        cores = host.get("cores") or 0
        mt = host.get("mem_total_mb") or 0
        mu = host.get("mem_used_mb") or 0
        cpu = host.get("cpu_pct") or 0.0
        d.set_pen(self._pens["dim"])
        d.text("gateway - {} cores - {:.1f} GB - load {}".format(cores, _gb(mt), host.get("load1", 0)),
               16, 46, W, 2)

        ram_pct = (mu / mt) if mt else 0.0
        self._gauge(126, 150, 70, min(1.0, cpu / 100.0),
                    "{:.0f}%".format(cpu), "CPU", None)
        self._gauge(354, 150, 70, ram_pct,
                    "{:.0f}%".format(ram_pct * 100), "RAM",
                    "{:.1f}/{:.0f}G".format(_gb(mu), _gb(mt)))

        # ranked consumers (sorted by the shim: cpu desc, then rss desc)
        d.set_pen(self._pens["accent"])
        d.text("TOP CONSUMERS", 16, 246, W, 2)
        d.set_pen(self._pens["dim"])
        d.text("cpu / mem", W - 130, 250, 120, 1)

        consumers = host.get("consumers") or []
        y0 = 274
        row_h = 30
        max_rows = max(1, (H - y0 - 22) // row_h)
        if self._scroll > max(0, len(consumers) - max_rows):
            self._scroll = max(0, len(consumers) - max_rows)
        view = consumers[self._scroll:self._scroll + max_rows]
        max_rss = max((e.get("rss") or 0) for e in consumers) or 1

        y = y0
        for e in view:
            kind = e.get("kind") or "other"
            d.set_pen(self._pens["panel"])
            d.rectangle(10, y, W - 20, row_h - 4)
            barw = int((W - 20) * (e.get("rss") or 0) / max_rss)
            d.set_pen(self._kind_pens.get(kind, self._pens["dim"]))
            d.rectangle(10, y, max(2, barw), row_h - 4)
            d.set_pen(self._pens["text"])
            d.text(theme.ascii_only(e.get("label") or "?")[:20], 16, y + 6, W - 160, 2)
            cpu_e = e.get("cpu") or 0
            cpen = self._pens["err"] if cpu_e >= 50 else (self._pens["amber"] if cpu_e >= 15 else self._pens["text"])
            d.set_pen(cpen)
            d.text("{:.0f}%".format(cpu_e), W - 150, y + 9, 50, 2)
            d.set_pen(self._pens["dim"])
            d.text(_short(e.get("rss")), W - 92, y + 9, 88, 2)
            y += row_h

        # footer: shared-pool breakdown (gateway = all chat agents together)
        g = host.get("gateway", {})
        v = host.get("voip_total", {})
        b = host.get("browser", {})
        d.set_pen(self._pens["dim"])
        foot = "gw(all chat) {} - voip x18 {} - brave {}".format(
            _short(g.get("rss")), _short(v.get("rss")), _short(b.get("rss")))
        d.text(foot, 16, H - 18, W, 1)
        if len(consumers) > max_rows:
            d.text("U/D", W - 44, H - 18, 44, 1)
