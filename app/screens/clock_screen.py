import machine

from app.screens.base import Screen
from app import theme

# US Eastern with automatic DST. Set FIXED_OFFSET to a whole-hour int (e.g. -5)
# to pin a zone and skip the DST rule; leave None to use the US ET rules below.
FIXED_OFFSET = None

# QlockTwo-style grid. Each tile is (key, label); keys are unique so the two
# FIVE/TEN tiles (minute vs hour) light independently. Rows render top-to-bottom
# and words left-to-right, so any lit phrase reads in natural reading order.
ROWS = [
    [("IT", "IT"), ("IS", "IS")],
    [("M_HALF", "HALF"), ("M_TEN", "TEN"), ("M_QUARTER", "QUARTER")],
    [("M_TWENTY", "TWENTY"), ("M_FIVE", "FIVE")],
    [("PAST", "PAST"), ("TO", "TO")],
    [("H1", "ONE"), ("H2", "TWO"), ("H3", "THREE")],
    [("H4", "FOUR"), ("H5", "FIVE"), ("H6", "SIX")],
    [("H7", "SEVEN"), ("H8", "EIGHT"), ("H9", "NINE")],
    [("H10", "TEN"), ("H11", "ELEVEN"), ("H12", "TWELVE")],
    [("OCLOCK", "OCLOCK")],
]

# index by hour % 12  (0 -> TWELVE, 1 -> ONE, ... 11 -> ELEVEN)
HOUR_KEYS = ["H12", "H1", "H2", "H3", "H4", "H5", "H6", "H7", "H8", "H9", "H10", "H11"]


def _dow(y, m, d):
    """Sakamoto's algorithm; 0=Sunday .. 6=Saturday."""
    t = [0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4]
    if m < 3:
        y -= 1
    return (y + y // 4 - y // 100 + y // 400 + t[m - 1] + d) % 7


def _nth_sunday(y, m, n):
    first = ((7 - _dow(y, m, 1)) % 7) + 1   # day-of-month of the first Sunday
    return first + 7 * (n - 1)


def _us_dst(y, m, d, hour_utc):
    """EDT runs from 2am local on the 2nd Sun of Mar (07:00 UTC) to 2am local on
    the 1st Sun of Nov (06:00 UTC). Transition edge resolved against UTC hour."""
    if m < 3 or m > 11:
        return False
    if 3 < m < 11:
        return True
    if m == 3:
        s = _nth_sunday(y, 3, 2)
        return d > s or (d == s and hour_utc >= 7)
    s = _nth_sunday(y, 11, 1)
    return d < s or (d == s and hour_utc < 6)


def _local(ts):
    """RTC is UTC (set by NTP). Return wall-clock (hour, minute, second)."""
    y, mo, d, hh, mm, ss = ts[0], ts[1], ts[2], ts[4], ts[5], ts[6]
    if FIXED_OFFSET is not None:
        off = FIXED_OFFSET
    else:
        off = -4 if _us_dst(y, mo, d, hh) else -5
    return (hh + off) % 24, mm, ss


def _phrase(hour, minute):
    """Set of tile keys lit for the current time, five-minute QlockTwo rounding."""
    h12 = hour % 12
    nxt = (h12 + 1) % 12
    out = {"IT", "IS"}
    if minute < 3:
        out |= {HOUR_KEYS[h12], "OCLOCK"}
    elif minute < 8:
        out |= {"M_FIVE", "PAST", HOUR_KEYS[h12]}
    elif minute < 13:
        out |= {"M_TEN", "PAST", HOUR_KEYS[h12]}
    elif minute < 18:
        out |= {"M_QUARTER", "PAST", HOUR_KEYS[h12]}
    elif minute < 23:
        out |= {"M_TWENTY", "PAST", HOUR_KEYS[h12]}
    elif minute < 28:
        out |= {"M_TWENTY", "M_FIVE", "PAST", HOUR_KEYS[h12]}
    elif minute < 33:
        out |= {"M_HALF", "PAST", HOUR_KEYS[h12]}
    elif minute < 38:
        out |= {"M_TWENTY", "M_FIVE", "TO", HOUR_KEYS[nxt]}
    elif minute < 43:
        out |= {"M_TWENTY", "TO", HOUR_KEYS[nxt]}
    elif minute < 48:
        out |= {"M_QUARTER", "TO", HOUR_KEYS[nxt]}
    elif minute < 53:
        out |= {"M_TEN", "TO", HOUR_KEYS[nxt]}
    elif minute < 58:
        out |= {"M_FIVE", "TO", HOUR_KEYS[nxt]}
    else:
        out |= {HOUR_KEYS[nxt], "OCLOCK"}
    return out


class ClockScreen(Screen):
    name = "clock"
    accent = theme.ACCENTS["clock"]

    def __init__(self, ctx):
        super().__init__(ctx)
        self._pens = None
        self._layout = None
        self._rtc = machine.RTC()

    def _ensure(self):
        if self._pens is not None:
            return
        d = self.ctx.display
        self._pens = {
            "bg": d.create_pen(*theme.BG),
            "dim": d.create_pen(0x22, 0x26, 0x2e),
            "hour": d.create_pen(*theme.ACCENTS["dgx"]),
            "min": d.create_pen(*theme.ACCENTS["openclaw"]),
            "sec": d.create_pen(*theme.ACCENTS["altitude"]),
            "text": d.create_pen(*theme.TEXT),
        }
        d.set_font("bitmap8")
        self._layout = self._compute_layout()

    def _compute_layout(self):
        d = self.ctx.display
        W, H = self.ctx.W, self.ctx.H
        pad = 14
        # biggest scale whose widest row still fits across the screen
        scale = 2
        for s in (4, 3, 2):
            sp = 6 + s * 2
            if all(sum(d.measure_text(lbl, s) for _, lbl in row) + sp * (len(row) - 1)
                   <= W - 2 * pad for row in ROWS):
                scale = s
                break
        sp = 6 + scale * 2
        ch = 8 * scale
        n = len(ROWS)
        top, bottom = 8, 40                 # bottom band reserved for digital readout
        step = (H - top - bottom) // n
        out = []
        for ri, row in enumerate(ROWS):
            rw = sum(d.measure_text(lbl, scale) for _, lbl in row) + sp * (len(row) - 1)
            x = (W - rw) // 2
            y = top + ri * step + (step - ch) // 2
            for key, lbl in row:
                out.append((key, lbl, x, y, scale))
                x += d.measure_text(lbl, scale) + sp
        return out

    def draw(self):
        self._ensure()
        d = self.ctx.display
        W, H = self.ctx.W, self.ctx.H

        hour, minute, second = _local(self._rtc.datetime())
        lit = _phrase(hour, minute)

        d.set_pen(self._pens["bg"])
        d.clear()
        for key, lbl, x, y, scale in self._layout:
            if key in lit:
                if key in ("IT", "IS"):
                    d.set_pen(self._pens["text"])
                elif key == "OCLOCK" or key.startswith("H"):
                    d.set_pen(self._pens["hour"])
                else:
                    d.set_pen(self._pens["min"])
            else:
                d.set_pen(self._pens["dim"])
            d.text(lbl, x, y, W, scale)

        d.set_pen(self._pens["sec"])
        d.text("{:02d}:{:02d}:{:02d}".format(hour, minute, second), W - 150, H - 30, 150, 2)
