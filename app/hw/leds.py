import time

NUM_LEDS = 7


class Leds:
    """Drives the 7 back LEDs. Modes:
       solid(rgb)      - all LEDs one color (used by per-screen accent)
       pulse(rgb)      - breathing
       rainbow()       - hue sweep
       columns(list)   - explicit rgb per LED (used by image sampler)
    """
    def __init__(self, presto):
        self.presto = presto
        try:
            presto.auto_ambient_leds(False)
        except Exception:
            pass
        self.brightness = 1.0
        self.mode = "solid"
        self.color = (0, 0, 0)
        self.cols = [(0, 0, 0)] * NUM_LEDS
        self._t0 = time.ticks_ms()

    def set_brightness(self, b):
        self.brightness = max(0.0, min(1.0, b))

    def solid(self, rgb):
        self.mode = "solid"
        self.color = rgb

    def pulse(self, rgb):
        self.mode = "pulse"
        self.color = rgb

    def rainbow(self):
        self.mode = "rainbow"

    def columns(self, cols):
        self.mode = "cols"
        self.cols = list(cols)[:NUM_LEDS] + [(0, 0, 0)] * max(0, NUM_LEDS - len(cols))

    def off(self):
        self.solid((0, 0, 0))

    def tick(self):
        b = self.brightness
        if self.mode == "solid":
            r, g, bl = self.color
            for i in range(NUM_LEDS):
                self.presto.set_led_rgb(i, int(r * b), int(g * b), int(bl * b))
        elif self.mode == "pulse":
            phase = (time.ticks_diff(time.ticks_ms(), self._t0) % 3000) / 3000.0
            import math
            k = (math.sin(phase * 2 * math.pi) + 1) / 2 * 0.7 + 0.3
            r, g, bl = self.color
            for i in range(NUM_LEDS):
                self.presto.set_led_rgb(i, int(r * b * k), int(g * b * k), int(bl * b * k))
        elif self.mode == "rainbow":
            phase = (time.ticks_diff(time.ticks_ms(), self._t0) % 6000) / 6000.0
            for i in range(NUM_LEDS):
                h = (phase + i / NUM_LEDS) % 1.0
                self.presto.set_led_hsv(i, h, 1.0, b)
        elif self.mode == "cols":
            for i, (r, g, bl) in enumerate(self.cols):
                self.presto.set_led_rgb(i, int(r * b), int(g * b), int(bl * b))
