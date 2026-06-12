import time

from app.screens.base import Screen
from app import theme


class NewsScreen(Screen):
    name = "news"
    accent = theme.ACCENTS["news"]
    sources = ("news",)

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
            "text": d.create_pen(*theme.TEXT),
            "dim": d.create_pen(*theme.TEXT_DIM),
            "accent": d.create_pen(*self.accent),
            "err": d.create_pen(*theme.ERR_RED),
        }

    def on_pad(self, key):
        if key == "U":
            self._scroll = max(0, self._scroll - 1)
        elif key == "D":
            self._scroll += 1

    def _wrap(self, text, w, scale, max_lines):
        d = self.ctx.display
        words = theme.ascii_only(text).split()
        lines = []
        cur = ""
        i = 0
        while i < len(words):
            trial = words[i] if not cur else cur + " " + words[i]
            if not cur or d.measure_text(trial, scale) <= w:
                cur = trial
                i += 1
            else:
                lines.append(cur)
                cur = ""
                if len(lines) >= max_lines:
                    break
        if cur and len(lines) < max_lines:
            lines.append(cur)
            i = len(words)
        if i < len(words) and lines:                 # truncated -> ellipsize last line
            last = lines[-1]
            while last and d.measure_text(last + "...", scale) > w:
                last = last[:-1].rstrip()
            lines[-1] = last + "..."
        return lines

    def draw(self):
        self._ensure_pens()
        d = self.ctx.display
        W, H = self.ctx.W, self.ctx.H
        s = self.ctx.state

        d.set_pen(self._pens["bg"])
        d.clear()
        d.set_pen(self._pens["accent"])
        d.text("AI NEWS", 16, 14, W, 3)

        stories = getattr(s, "news", None) or []
        err = getattr(s, "news_err", None)
        ts = getattr(s, "news_ts", 0)
        d.set_pen(self._pens["dim"])
        age = int(time.time() - ts) if ts else None
        sub = "Hacker News - {} stories".format(len(stories))
        if age is not None:
            sub += " - {}s".format(age)
        d.text(sub, 16, 48, W, 2)

        if err and not stories:
            d.set_pen(self._pens["err"])
            d.text("news error:", 16, 84, W, 2)
            d.text(str(err)[:60], 16, 108, W - 32, 2)
            return
        if not stories:
            d.set_pen(self._pens["dim"])
            d.text("loading trending AI stories...", 16, 90, W - 32, 2)
            return

        y0 = 78
        row_h = 76
        max_rows = max(1, (H - y0 - 16) // row_h)
        if self._scroll > max(0, len(stories) - max_rows):
            self._scroll = max(0, len(stories) - max_rows)
        view = stories[self._scroll:self._scroll + max_rows]
        y = y0
        for st in view:
            d.set_pen(self._pens["panel"])
            d.rectangle(12, y, W - 24, row_h - 8)

            d.set_pen(self._pens["accent"])
            d.text(str(st.get("points", 0)), 22, y + 10, 70, 3)
            d.set_pen(self._pens["dim"])
            d.text("pts", 22, y + 44, 70, 1)

            tx = 96
            lines = self._wrap(st.get("title", ""), W - tx - 16, 2, 2)
            d.set_pen(self._pens["text"])
            for li, line in enumerate(lines):
                d.text(line, tx, y + 6 + li * 22, W - tx - 16, 2)

            d.set_pen(self._pens["dim"])
            meta = "{} comments".format(st.get("comments", 0))
            author = theme.ascii_only(st.get("author") or "")
            if author:
                meta += " - " + author
            d.text(meta, tx, y + 52, W - tx - 16, 1)
            y += row_h

        if len(stories) > max_rows:
            d.set_pen(self._pens["dim"])
            d.text("U/D  {}-{}/{}".format(self._scroll + 1, self._scroll + len(view), len(stories)),
                   W - 150, H - 18, 150, 1)
