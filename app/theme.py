"""Per-screen palettes. Each screen exposes an accent (r,g,b); the LED driver
samples it (with optional ambient-light dimming) to drive the 7 back LEDs."""

import math

ACCENTS = {
    "dgx":      (0x76, 0xb9, 0x00),   # nvidia green
    "openclaw": (0xff, 0x6b, 0x35),   # warm orange
    "resources": (0x35, 0xc8, 0xff),  # system cyan
    "kuma":     (0x3a, 0xd1, 0x9b),   # uptime green-teal
    "crypto":   (0xf7, 0x93, 0x1a),   # bitcoin gold
    "env":      (0x4d, 0xc9, 0xb0),   # teal
    "altitude": (0x56, 0x9f, 0xc9),   # sky blue
    "news":     (0x9b, 0x6d, 0xff),   # indigo / violet
    "random":   (0xff, 0x6f, 0xd5),   # entropy magenta
    "lights":   (0xff, 0xff, 0xff),   # white, gets overridden by image sampler
    "clock":    (0xe0, 0xe0, 0xe0),   # near-white
    "settings": (0x90, 0x90, 0xb0),   # muted lavender
}

BG = (0x08, 0x0a, 0x10)
PANEL = (0x12, 0x16, 0x1f)
PANEL_HI = (0x1e, 0x24, 0x33)
TEXT = (0xe0, 0xe6, 0xee)
TEXT_DIM = (0x88, 0x90, 0x9c)
OK_GREEN = (0x4a, 0xd4, 0x8a)
WARN_AMBER = (0xff, 0xb3, 0x3a)
ERR_RED = (0xff, 0x5a, 0x5a)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def scale(rgb, t):
    return tuple(max(0, min(255, int(c * t))) for c in rgb)


def ascii_only(s):
    # bitmap8 font is ASCII-only; drop emoji / unicode so they don't render as garbage
    if not s:
        return ""
    return "".join(c if 32 <= ord(c) < 127 else "" for c in str(s))


def load_rgb(pct):
    # green -> amber -> red as utilization climbs (pct is 0..1)
    if pct < 0.6:
        return OK_GREEN
    if pct < 0.85:
        return WARN_AMBER
    return ERR_RED


# Segmented donut gauge built from circles only (PicoGraphics has no arc/polygon
# we rely on). Unit offsets precomputed once; start at 12 o'clock, go clockwise.
_RING_N = 24
_RING_UNIT = [(math.cos(-math.pi / 2 + 2 * math.pi * i / _RING_N),
               math.sin(-math.pi / 2 + 2 * math.pi * i / _RING_N)) for i in range(_RING_N)]


def ring_gauge(d, cx, cy, r, pct, fill_pen, track_pen, dot_r=6):
    f = int(round(max(0.0, min(1.0, pct)) * _RING_N))
    for i in range(_RING_N):
        c, s = _RING_UNIT[i]
        d.set_pen(fill_pen if i < f else track_pen)
        d.circle(int(cx + r * c), int(cy + r * s), dot_r)
