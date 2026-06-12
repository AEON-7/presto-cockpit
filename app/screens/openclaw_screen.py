import time

from app.screens.base import Screen
from app import theme
from app.net import openclaw as net_oc


def _ktok(n):
    if not n:
        return "0"
    if n >= 1_000_000:
        return "{:.1f}M".format(n / 1_000_000)
    if n >= 1000:
        return "{:.1f}k".format(n / 1000)
    return str(int(n))


def _age(ms):
    if ms is None:
        return "idle"
    s = ms // 1000
    if s < 60:
        return "{}s ago".format(s)
    if s < 3600:
        return "{}m ago".format(s // 60)
    if s < 86400:
        return "{}h ago".format(s // 3600)
    return "{}d ago".format(s // 86400)


class OpenClawScreen(Screen):
    name = "openclaw"
    accent = theme.ACCENTS["openclaw"]
    sources = ("openclaw",)

    def __init__(self, ctx):
        super().__init__(ctx)
        self._pens = None
        self._scroll = 0
        self._detail = None          # agent id when drilled into the detail view
        self._detail_sessions = None
        self._detail_err = None
        self._dscroll = 0

    def leave(self):
        self._detail = None
        self._dscroll = 0

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
            "off": d.create_pen(0x40, 0x44, 0x4c),
            "err": d.create_pen(*theme.ERR_RED),
        }

    def on_pad(self, key):
        if self._detail is not None:
            if key == "U":
                self._dscroll = max(0, self._dscroll - 1)
            elif key == "D":
                self._dscroll += 1
            return
        if key == "U":
            self._scroll = max(0, self._scroll - 1)
        elif key == "D":
            self._scroll += 1

    def on_touch(self, x, y):
        if self._detail is not None:
            self._detail = None       # tap anywhere returns to the agent list
            return
        agents = self.ctx.state.openclaw_agents or []
        if not agents or y < 78:
            return
        row_h = 72
        max_rows = max(1, (self.ctx.H - 78 - 130) // row_h)
        idx = (y - 78) // row_h
        if idx >= max_rows:
            return
        ai = self._scroll + idx
        if ai < len(agents):
            self._open_detail(agents[ai].get("id"))

    def _open_detail(self, aid):
        self._detail = aid
        self._detail_err = None
        self._detail_sessions = None
        self._dscroll = 0
        if not aid:
            self._detail_err = "no id"
            return
        oc = self.ctx.secrets.get("openclaw") or {}
        url = oc.get("url")
        if not url:
            self._detail_err = "no url"
            return
        data, err = net_oc.agent_detail(url, aid, oc.get("bearer"))
        if err:
            self._detail_err = err
        else:
            self._detail_sessions = (data or {}).get("sessions", [])

    def _agent_by_id(self, aid):
        for a in (self.ctx.state.openclaw_agents or []):
            if a.get("id") == aid:
                return a
        return {}

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
        d.text("OPENCLAW", 16, 14, W, 3)

        agents = s.openclaw_agents or []
        tasks = s.openclaw_tasks or {}
        active_n = sum(1 for a in agents if a.get("active"))
        d.set_pen(self._pens["dim"])
        age = int(time.time() - s.openclaw_ts) if s.openclaw_ts else None
        sub = "{} agents - {} active".format(len(agents), active_n)
        if age is not None:
            sub += " - {}s".format(age)
        d.text(sub, 16, 48, W, 2)

        if s.openclaw_err and not agents:
            d.set_pen(self._pens["err"])
            d.text("shim error:", 16, 84, W, 2)
            d.text(str(s.openclaw_err)[:60], 16, 108, W - 32, 2)
            d.set_pen(self._pens["dim"])
            d.text("is openclaw-shim running on the gateway?", 16, 140, W - 32, 1)
            return

        y = 78
        row_h = 72
        max_rows = max(1, (H - y - 130) // row_h)  # leave room for the tokens panel + task footer
        view = agents[self._scroll:self._scroll + max_rows]
        for a in view:
            d.set_pen(self._pens["panel"])
            d.rectangle(12, y, W - 24, row_h - 6)
            if a.get("working") or a.get("on_call"):
                color = self._pens["accent"]      # live: driving the model right now
            elif a.get("active"):
                color = self._pens["ok"]
            else:
                color = self._pens["off"]
            d.set_pen(color)
            d.circle(28, y + 20, 6)

            d.set_pen(self._pens["text"])
            label = theme.ascii_only(a.get("name") or a.get("id") or "?")
            d.text(label[:22], 44, y + 8, W - 150, 2)

            d.set_pen(self._pens["dim"])
            model = theme.ascii_only(a.get("model") or "")[:18]
            prov = theme.ascii_only(a.get("provider") or "")[:6]
            d.text("{} - {}".format(prov, model) if prov else model, 44, y + 32, W - 150, 1)

            last = a.get("last_seen_s_ago")
            if a.get("on_call"):
                last_s = "ON CALL"
            elif a.get("working"):
                last_s = "WORKING"
            elif last is None:
                last_s = "idle -"
            elif last < 60:
                last_s = "{}s ago".format(last)
            elif last < 3600:
                last_s = "{}m ago".format(last // 60)
            else:
                last_s = "{}h ago".format(last // 3600)
            live = a.get("on_call") or a.get("working")
            d.set_pen(self._pens["accent"] if live else self._pens["dim"])
            d.text(last_s, 44, y + 50, 92, 1)
            d.set_pen(self._pens["dim"])
            sess_line = "{}/{} sess - {} ctx".format(
                a.get("active_sessions", 0), a.get("sessions", 0), _ktok(a.get("total_tokens")))
            runs = a.get("runs_active") or 0
            subs = a.get("subagents_active") or 0
            if runs or subs:
                sess_line += " - R{}".format(runs) + ("/S{}".format(subs) if subs else "")
            d.text(sess_line, 140, y + 50, W - 272, 1)

            tok_s = a.get("tok_s") or 0
            pp = a.get("pp_tok_s") or 0
            d.set_pen(self._pens["accent"] if tok_s > 0.5 else self._pens["dim"])
            d.text("{:.1f}".format(tok_s), W - 130, y + 8, 118, 3)
            d.set_pen(self._pens["dim"])
            d.text("gen tok/s", W - 128, y + 34, 90, 1)
            d.set_pen(self._pens["accent"] if pp > 0.5 else self._pens["dim"])
            d.text("rd {:.0f}/s".format(pp), W - 128, y + 50, 110, 1)
            y += row_h

        # --- TOKENS USED panel (7d / 30d / 1y) ---
        u = s.openclaw_usage or {}
        uy = H - 116
        d.set_pen(self._pens["dim"])
        d.text("TOKENS USED", 16, uy, W, 2)
        dt = u.get("days_tracked", 0) if u else 0
        a7 = u.get("approx_7d", 0) if u else 0
        a30 = u.get("approx_30d", 0) if u else 0  # ~= all retained session history (~30d)

        def _val(window_days, ledger_key, approx_val):
            lv = u.get(ledger_key, 0) if u else 0
            if u and dt >= window_days:        # ledger fully covers this window -> exact
                return lv, ""
            return (lv if lv > approx_val else approx_val), "~"

        cols = (("7D", _val(7, "ledger_7d", a7)),
                ("30D", _val(30, "ledger_30d", a30)),
                ("1Y", _val(365, "ledger_365d", a30)))
        cw = (W - 24) // 3
        for i, (label, (val, mark)) in enumerate(cols):
            x = 12 + i * cw
            d.set_pen(self._pens["dim"])
            d.text(label, x + 4, uy + 24, cw, 2)
            d.set_pen(self._pens["accent"])
            d.text(mark + _ktok(val), x + 4, uy + 42, cw, 3)
        since = u.get("tracked_since") if u else None
        d.set_pen(self._pens["dim"])
        d.text("~ = est. from ~30d sessions; exact ledger since {}".format(since or "today"),
               16, uy + 76, W, 1)

        # footer: global task state
        run = tasks.get("running", 0)
        q = tasks.get("queued", 0)
        act = tasks.get("active", 0)
        sub = tasks.get("subagents", 0)
        foot = "jobs: {}a {}r {}q - {} sub".format(act, run, q, sub)
        if tasks.get("total"):
            foot += " - {} total, {} fail".format(tasks.get("total"), tasks.get("failures", 0))
        d.set_pen(self._pens["dim"])
        d.text(foot, 16, H - 20, W, 1)
        if len(agents) > max_rows:
            d.text("U/D", W - 52, H - 20, 52, 1)

    def _draw_detail(self):
        d = self.ctx.display
        W, H = self.ctx.W, self.ctx.H
        a = self._agent_by_id(self._detail)

        d.set_pen(self._pens["bg"])
        d.clear()
        d.set_pen(self._pens["accent"])
        name = theme.ascii_only(a.get("name") or self._detail or "?")
        d.text(name[:18], 16, 14, W - 90, 3)
        d.set_pen(self._pens["dim"])
        d.text("< tap", W - 78, 22, 78, 2)

        prov = theme.ascii_only(a.get("provider") or "")
        model = theme.ascii_only(a.get("model") or "")
        d.text(("{} - {}".format(prov, model) if prov else model)[:46], 16, 50, W, 2)

        d.set_pen(self._pens["text"])
        d.text("gen {:.1f}/s   rd {:.0f}/s   {}/{} sess".format(
            a.get("tok_s") or 0, a.get("pp_tok_s") or 0,
            a.get("active_sessions") or 0, a.get("sessions") or 0), 16, 74, W - 16, 2)
        d.set_pen(self._pens["dim"])
        d.text("in {}  out {}  total {} tok".format(
            _ktok(a.get("in_tokens")), _ktok(a.get("out_tokens")), _ktok(a.get("total_tokens"))),
            16, 98, W - 16, 1)

        # live state + this agent's own process draw (voip; chat is shared)
        bits = []
        if a.get("on_call"):
            bits.append("ON CALL")
        elif a.get("working"):
            bits.append("WORKING")
        runs = a.get("runs_active") or 0
        subs = a.get("subagents_active") or 0
        if runs:
            bits.append("{} run{}".format(runs, "" if runs == 1 else "s"))
        if subs:
            bits.append("{} subagent{}".format(subs, "" if subs == 1 else "s"))
        proc_rss = a.get("proc_rss_mb")
        if proc_rss is not None:
            res = "voip proc: cpu {:.0f}%  ram {}M  (chat shared in gateway)".format(
                a.get("proc_cpu") or 0, proc_rss)
        else:
            res = "runs in shared gateway process"
        line = (" - ".join(bits) + "   |   " + res) if bits else res
        d.set_pen(self._pens["accent"] if (a.get("working") or a.get("on_call")) else self._pens["dim"])
        d.text(line, 16, 116, W - 16, 1)

        y = 138
        if self._detail_err:
            d.set_pen(self._pens["err"])
            d.text("detail error:", 16, y, W, 2)
            d.text(str(self._detail_err)[:56], 16, y + 22, W - 32, 1)
            return

        sess = self._detail_sessions or []
        d.set_pen(self._pens["text"])
        d.text("SESSIONS ({})".format(len(sess)), 16, y, W, 2)
        y += 26
        row_h = 54
        max_rows = max(1, (H - y - 28) // row_h)
        if self._dscroll > max(0, len(sess) - max_rows):
            self._dscroll = max(0, len(sess) - max_rows)
        view = sess[self._dscroll:self._dscroll + max_rows]
        for sd in view:
            d.set_pen(self._pens["panel"])
            d.rectangle(12, y, W - 24, row_h - 6)
            d.set_pen(self._pens["text"])
            label = theme.ascii_only(sd.get("key") or sd.get("kind") or "session")
            d.text(label[:30], 22, y + 6, W - 40, 2)
            d.set_pen(self._pens["dim"])
            line = "{} - {} tok".format(_age(sd.get("age_ms")), _ktok(sd.get("total_tokens")))
            ctx = sd.get("context_tokens")
            if ctx:
                line += " - ctx {}".format(_ktok(ctx))
            th = sd.get("thinking")
            if th and th != "off":
                line += " - think {}".format(th)
            if sd.get("aborted"):
                line += " - ABORTED"
            d.text(line[:60], 22, y + 30, W - 40, 1)
            y += row_h

        if len(sess) > max_rows:
            d.set_pen(self._pens["dim"])
            d.text("U/D  {}-{}/{}".format(self._dscroll + 1, self._dscroll + len(view), len(sess)),
                   W - 150, H - 18, 150, 1)
