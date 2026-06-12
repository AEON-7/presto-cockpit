import time

from app.screens.base import Screen
from app import theme
from app.lights.animations import ANIMATIONS
from app.lights.image_sampler import list_images


class LightsScreen(Screen):
    name = "lights"
    accent = theme.ACCENTS["lights"]

    MODES = ("animation", "image", "solid")

    def __init__(self, ctx):
        super().__init__(ctx)
        self._pens = None
        self._mode_i = 0
        self._anim_i = 0
        self._img_i = 0
        self._solid_h = 0.0
        self._t0 = time.ticks_ms()
        self._jpeg = None
        self._images = []
        self._last_img_load_ts = 0

    def enter(self):
        self._images = list_images()
        if self._mode() == "image":
            try:
                self.ctx.presto.auto_ambient_leds(True)
            except Exception:
                pass
        else:
            try:
                self.ctx.presto.auto_ambient_leds(False)
            except Exception:
                pass

    def leave(self):
        try:
            self.ctx.presto.auto_ambient_leds(False)
        except Exception:
            pass

    def _mode(self):
        return self.MODES[self._mode_i % len(self.MODES)]

    def on_pad(self, key):
        if key == "A":
            self._mode_i = (self._mode_i + 1) % len(self.MODES)
            self.enter()
        elif key == "U":
            if self._mode() == "animation":
                self._anim_i = (self._anim_i - 1) % len(ANIMATIONS)
            elif self._mode() == "image" and self._images:
                self._img_i = (self._img_i - 1) % len(self._images)
                self._jpeg = None
            else:
                self._solid_h = (self._solid_h + 1 / 12) % 1.0
        elif key == "D":
            if self._mode() == "animation":
                self._anim_i = (self._anim_i + 1) % len(ANIMATIONS)
            elif self._mode() == "image" and self._images:
                self._img_i = (self._img_i + 1) % len(self._images)
                self._jpeg = None
            else:
                self._solid_h = (self._solid_h - 1 / 12) % 1.0

    def on_touch(self, x, y):
        if x < self.ctx.W // 3:
            self.on_pad("U")
        elif x > 2 * self.ctx.W // 3:
            self.on_pad("D")
        else:
            self.on_pad("A")

    def _ensure_pens(self):
        if self._pens is not None:
            return
        d = self.ctx.display
        self._pens = {
            "text": d.create_pen(*theme.TEXT),
            "dim": d.create_pen(*theme.TEXT_DIM),
            "bg": d.create_pen(*theme.BG),
        }

    def _draw_image(self):
        d = self.ctx.display
        if not self._images:
            d.set_pen(self._pens["bg"])
            d.clear()
            d.set_pen(self._pens["text"])
            d.text("no jpgs in /images", 16, self.ctx.H // 2 - 10, self.ctx.W, 3)
            return
        path = self._images[self._img_i % len(self._images)]
        if self._jpeg is None:
            try:
                import jpegdec
                self._jpeg = jpegdec.JPEG(d)
                self._jpeg.open_file(path)
                self._last_img_load_ts = time.ticks_ms()
            except Exception as e:
                d.set_pen(self._pens["bg"])
                d.clear()
                d.set_pen(self._pens["text"])
                d.text("jpeg load err: " + str(e)[:30], 16, 80, self.ctx.W, 2)
                return
        try:
            import jpegdec
            self._jpeg.decode(0, 0, jpegdec.JPEG_SCALE_FULL, dither=True)
        except Exception as e:
            d.set_pen(self._pens["text"])
            d.text(str(e)[:60], 16, 16, self.ctx.W, 2)

    def draw(self):
        self._ensure_pens()
        d = self.ctx.display
        W, H = self.ctx.W, self.ctx.H
        m = self._mode()

        if m == "image":
            self._draw_image()
        elif m == "animation":
            anim = ANIMATIONS[self._anim_i % len(ANIMATIONS)]
            t = time.ticks_diff(time.ticks_ms(), self._t0)
            anim.draw(d, W, H, self.ctx.leds, t)
        else:
            from app.lights.animations import _hsv_rgb
            r, g, b = _hsv_rgb(self._solid_h, 0.9, 1.0)
            d.set_pen(d.create_pen(r, g, b))
            d.clear()
            self.ctx.leds.solid((r, g, b))

        d.set_pen(self._pens["text"])
        label = m.upper()
        if m == "animation":
            label += "  " + ANIMATIONS[self._anim_i % len(ANIMATIONS)].name
        elif m == "image" and self._images:
            name = self._images[self._img_i % len(self._images)].split("/")[-1]
            label += "  " + name
        d.text(label, 16, H - 30, W, 2)
        d.set_pen(self._pens["dim"])
        d.text("A: mode  U/D: choose", 16, H - 14, W, 1)
