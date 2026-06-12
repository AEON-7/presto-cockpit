import time

from app.screens.base import Screen
from app import theme


COIN_META = {
    "bitcoin":  ("BTC", (0xf7, 0x93, 0x1a)),
    "ethereum": ("ETH", (0x62, 0x7e, 0xea)),
    "monero":   ("XMR", (0xff, 0x66, 0x00)),
    "solana":   ("SOL", (0x9b, 0x4d, 0xff)),
}


def _fmt(p):
    if p is None:
        return "-"
    if p >= 10000:
        return "{:,.0f}".format(p).replace(",", ",")
    if p >= 100:
        return "{:,.1f}".format(p)
    if p >= 1:
        return "{:.2f}".format(p)
    return "{:.4f}".format(p)


class CryptoScreen(Screen):
    name = "crypto"
    accent = theme.ACCENTS["crypto"]
    sources = ("crypto",)

    def __init__(self, ctx):
        super().__init__(ctx)
        self._pens = None

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
            "up": d.create_pen(*theme.OK_GREEN),
            "down": d.create_pen(*theme.ERR_RED),
            "err": d.create_pen(*theme.ERR_RED),
        }
        for coin, (_sym, rgb) in COIN_META.items():
            self._pens["c_" + coin] = d.create_pen(*rgb)

    def draw(self):
        self._ensure_pens()
        d = self.ctx.display
        W, H = self.ctx.W, self.ctx.H
        s = self.ctx.state

        d.set_pen(self._pens["bg"])
        d.clear()
        d.set_pen(self._pens["accent"])
        d.text("MARKETS", 16, 14, W, 3)
        d.set_pen(self._pens["dim"])
        age = int(time.time() - s.crypto_ts) if s.crypto_ts else None
        d.text("USD - {}s ago".format(age) if age is not None else "USD - no data",
               16, 48, W, 2)

        coins = list(self.ctx.secrets.get("crypto", {}).get("ids") or COIN_META.keys())
        cell_w = (W - 30) // 2
        cell_h = (H - 100) // 2
        for i, coin in enumerate(coins[:4]):
            row = i // 2
            col = i % 2
            x = 12 + col * (cell_w + 6)
            y = 80 + row * (cell_h + 6)
            d.set_pen(self._pens["panel"])
            d.rectangle(x, y, cell_w, cell_h)
            sym, _rgb = COIN_META.get(coin, (coin.upper()[:4], (0x99, 0x99, 0x99)))
            d.set_pen(self._pens["c_" + coin] if ("c_" + coin) in self._pens else self._pens["accent"])
            d.text(sym, x + 12, y + 10, cell_w, 4)
            row_data = (s.crypto or {}).get(coin) or {}
            price = row_data.get("price")
            change = row_data.get("change_24h")
            d.set_pen(self._pens["text"])
            d.text("$" + _fmt(price), x + 12, y + 60, cell_w, 4)
            if change is None:
                d.set_pen(self._pens["dim"])
                d.text("-", x + 12, y + cell_h - 30, cell_w, 2)
            else:
                d.set_pen(self._pens["up"] if change >= 0 else self._pens["down"])
                d.text("{:+.2f}% 24h".format(change), x + 12, y + cell_h - 30, cell_w, 2)

        if s.crypto_err:
            d.set_pen(self._pens["err"])
            d.text(str(s.crypto_err)[:60], 16, H - 22, W, 1)
