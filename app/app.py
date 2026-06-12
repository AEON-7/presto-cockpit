import time
import machine

from presto import Presto

from app import theme
from app.hw.sensors import Sensors
from app.hw.pad import Pad
from app.hw.leds import Leds
from app.state import State
from app.net import dgx as net_dgx, openclaw as net_oc, crypto as net_crypto, news as net_news


SCREENS_ORDER = ["dgx", "openclaw", "resources", "news", "crypto", "env", "clock", "settings"]


class Ctx:
    """Per-screen handle. Bundles display, presto, state, secrets, fonts."""
    def __init__(self, presto, display, state, secrets, leds, sensors, pad):
        self.presto = presto
        self.display = display
        self.state = state
        self.secrets = secrets
        self.leds = leds
        self.sensors = sensors
        self.pad = pad
        self.W, self.H = display.get_bounds()


class App:
    def __init__(self):
        try:
            from boot import SECRETS
        except Exception:
            SECRETS = None
        self.secrets = SECRETS or {}

        self.presto = Presto(full_res=True, ambient_light=False)
        self.display = self.presto.display
        self.W, self.H = self.display.get_bounds()

        self.state = State()

        self._splash("starting...")
        wifi_ok = self._wifi()
        self.state.wifi_connected = wifi_ok
        if wifi_ok:
            self._splash("syncing time...")
            self._ntp()

        try:
            i2c = machine.I2C()
        except Exception:
            i2c = None

        self.sensors = Sensors()
        self.pad = Pad(self.sensors.i2c if self.sensors.i2c else i2c)
        self.leds = Leds(self.presto)

        self.ctx = Ctx(self.presto, self.display, self.state, self.secrets,
                       self.leds, self.sensors, self.pad)

        self._last_poll = {"dgx": 0, "openclaw": 0, "news": 0, "crypto": 0, "sensors": 0}
        self.screens = self._load_screens()
        self.idx = 0
        self._enter(self.idx)

        self._user_btn = None
        try:
            self._user_btn = machine.Pin(46, machine.Pin.IN)
        except Exception:
            pass
        self._user_btn_prev = 1
        self._touch_prev = False
        self._last_backlight = None
        self._last_wifi_try = 0
        self._wifi_tries = 0
        # Battery monitoring: NOT POSSIBLE natively on the Presto. Confirmed
        # against the Pimoroni source (boards/presto/* + docs/presto.md +
        # forum): the board has no on-board voltage divider on any ADC pin and
        # no charger IC — the LiPo JST is a 3V-5.5V power-source input only.
        # A prior version of this code mis-read ADC(2)/GP28 as if it were a
        # VSYS divider and showed a fictitious percentage; pulled out. Real
        # monitoring needs an external I2C fuel gauge (e.g., MAX17048) on the
        # Qw/ST bus, and real charging needs an external pass-through charger.

    def _splash(self, msg):
        BG = self.display.create_pen(*theme.BG)
        FG = self.display.create_pen(*theme.TEXT)
        self.display.set_pen(BG)
        self.display.clear()
        self.display.set_pen(FG)
        self.display.text("PRESTO COCKPIT", 16, self.H // 2 - 30, self.W, 3)
        self.display.text(msg, 16, self.H // 2 + 10, self.W, 2)
        try:
            self.presto.update()
        except Exception:
            pass

    def _wifi(self):
        # Raw WLAN with a clean radio cycle + bounded timeout, so a bad/unreachable
        # AP can never hang boot (presto.connect()/WPA3 can block forever otherwise).
        import network
        w = self.secrets.get("wifi") or {}
        ssid = w.get("ssid")
        pwd = w.get("password", "")
        if not ssid:
            print("no wifi ssid in secrets.json")
            return False
        try:
            network.country(w.get("country", "US"))
        except Exception:
            pass
        wlan = network.WLAN(network.STA_IF)
        try:
            wlan.active(False)
            time.sleep(1)
        except Exception:
            pass
        wlan.active(True)
        time.sleep(2)
        self._wlan = wlan
        try:
            wlan.connect(ssid, pwd)
        except Exception as e:
            print("wifi connect err:", e)
            return False
        deadline = time.ticks_add(time.ticks_ms(), 20000)
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            if wlan.isconnected():
                print("wifi connected:", wlan.ifconfig()[0])
                return True
            self._splash("wifi: connecting...")
            time.sleep_ms(400)
        print("wifi timed out (status {}); booting offline".format(wlan.status()))
        return False

    def _ntp(self):
        try:
            import ntptime
            ntptime.settime()
            self.state.time_synced = True
        except Exception as e:
            print("ntp failed:", e)

    def _load_screens(self):
        from app.screens.dgx_screen import DGXScreen
        from app.screens.openclaw_screen import OpenClawScreen
        from app.screens.resources_screen import ResourcesScreen
        from app.screens.news_screen import NewsScreen
        from app.screens.crypto_screen import CryptoScreen
        from app.screens.env_screen import EnvScreen
        from app.screens.clock_screen import ClockScreen
        from app.screens.settings_screen import SettingsScreen
        return [
            DGXScreen(self.ctx),
            OpenClawScreen(self.ctx),
            ResourcesScreen(self.ctx),
            NewsScreen(self.ctx),
            CryptoScreen(self.ctx),
            EnvScreen(self.ctx),
            ClockScreen(self.ctx),
            SettingsScreen(self.ctx),
        ]

    def _enter(self, i):
        self.idx = i % len(self.screens)
        screen = self.screens[self.idx]
        for src in getattr(screen, "sources", ()):  # refresh its feed(s) immediately on entry
            if src in self._last_poll:
                self._last_poll[src] = 0
        screen.enter()
        self.leds.solid(screen.accent)

    def _nav(self, delta):
        self.screens[self.idx].leave()
        self._enter(self.idx + delta)

    def _maybe_poll(self):
        # Only the active screen's network feeds are polled; sensors are always
        # read (cheap local I2C, needed for env/altitude + ambient auto-dim).
        now = time.time()
        s = self.state
        secrets = self.secrets
        active = self.screens[self.idx].sources

        if "dgx" in active:
            dgx_cfg = secrets.get("dgx") or {}
            interval = dgx_cfg.get("poll_interval_s", 1.0)
            if s.dgx_err:
                interval = max(interval, 10.0)   # back off a failing endpoint so its timeout doesn't stall the UI
            if dgx_cfg.get("url") and now - self._last_poll["dgx"] >= interval:
                data, err = net_dgx.fetch(dgx_cfg["url"])
                if err:
                    s.dgx_err = err          # keep last-good s.dgx; a transient timeout shouldn't blank the screen
                else:
                    s.dgx, s.dgx_err, s.dgx_ts = data, None, now
                self._last_poll["dgx"] = now
                return

        if "openclaw" in active:
            oc_cfg = secrets.get("openclaw") or {}
            interval = oc_cfg.get("poll_interval_s", 2.0)
            if s.openclaw_err:
                interval = max(interval, 10.0)
            if oc_cfg.get("url") and now - self._last_poll["openclaw"] >= interval:
                data, err = net_oc.fetch(oc_cfg["url"], oc_cfg.get("bearer"))
                if err:
                    s.openclaw_err = err
                else:
                    s.openclaw_agents = data.get("agents", [])
                    s.openclaw_tasks = data.get("tasks")
                    s.openclaw_usage = data.get("usage")
                    s.openclaw_host = data.get("host")
                    s.openclaw_err = None
                    s.openclaw_ts = now
                self._last_poll["openclaw"] = now
                return

        if "news" in active:
            # public HN endpoint, no secret needed; refresh every ~5 min
            if now - self._last_poll["news"] >= 300.0:
                data, err = net_news.fetch()
                if err:
                    s.news_err = err
                else:
                    s.news, s.news_err, s.news_ts = data, None, now
                self._last_poll["news"] = now
                return

        if "crypto" in active:
            cy_cfg = secrets.get("crypto") or {}
            if cy_cfg.get("ids") and now - self._last_poll["crypto"] >= cy_cfg.get("poll_interval_s", 30.0):
                data, err = net_crypto.fetch(cy_cfg["ids"], cy_cfg.get("vs", "usd"))
                if err:
                    s.crypto_err = err       # keep last-good prices on a transient timeout
                else:
                    s.crypto, s.crypto_err, s.crypto_ts = data, None, now
                self._last_poll["crypto"] = now
                return

        if now - self._last_poll["sensors"] >= 0.1:
            self.state.sensors_ok = self.sensors.read(self.state.sensors)
            self._last_poll["sensors"] = now

    def _input(self):
        self.presto.touch_poll()
        try:
            tx, ty, td = self.presto.touch_a
        except Exception:
            tx = ty = td = 0
        screen = self.screens[self.idx]

        if td and not self._touch_prev:   # fire once per tap (rising edge)
            screen.on_touch(tx, ty)
        self._touch_prev = bool(td)

        if self._user_btn is not None:
            v = self._user_btn.value()
            if v == 0 and self._user_btn_prev == 1:
                self._nav(1)
            self._user_btn_prev = v

        for key in self.pad.poll():
            if key == "L":
                self._nav(-1)
            elif key == "R":
                self._nav(1)
            elif key == "+":
                self.leds.set_brightness(min(1.0, self.leds.brightness + 0.1))
            elif key == "-":
                self.leds.set_brightness(max(0.0, self.leds.brightness - 0.1))
            else:
                screen.on_pad(key)

    def _auto_dim(self):
        lights = self.secrets.get("lights", {})
        if not lights.get("auto_dim_from_ambient", True):
            self._set_backlight(1.0)
            return
        default_b = lights.get("default_brightness", 0.6)
        lux = self.state.sensors.get("lux")
        # LTR559 here is unreliable (reads ~0 / noisy). Treat anything below a real
        # indoor level as "no usable reading" so sensor noise can't toggle branches
        # and flicker the panel; hold a readable backlight instead of dimming.
        if not lux or lux < 8:
            self.leds.set_brightness(default_b)
            self._set_backlight(1.0)
            return
        b = max(0.08, min(1.0, lux / 250.0))
        self.leds.set_brightness(b * default_b)
        self._set_backlight(max(0.5, min(1.0, lux / 400.0)))

    def _set_backlight(self, value):
        # Calling set_backlight every frame visibly flickers the panel; only touch
        # the PWM when the (quantized) target actually changes.
        value = round(value, 2)
        if value == self._last_backlight:
            return
        self._last_backlight = value
        try:
            self.presto.set_backlight(value)
        except Exception:
            pass

    def _wifi_tick(self):
        # Self-heal WiFi: the radio can drop after boot and never recover otherwise,
        # leaving every screen with EHOSTUNREACH. Non-blocking reconnect, throttled.
        try:
            if self._wlan.isconnected():
                self.state.wifi_connected = True
                self._wifi_tries = 0
                return
        except Exception:
            pass
        self.state.wifi_connected = False
        now = time.time()
        if now - self._last_wifi_try < 10:
            return
        self._last_wifi_try = now
        self._wifi_tries += 1
        w = self.secrets.get("wifi") or {}
        try:
            if self._wifi_tries % 6 == 0:   # periodic radio kick for a wedged cyw43
                self._wlan.active(False)
                self._wlan.active(True)
            self._wlan.connect(w.get("ssid"), w.get("password", ""))
            print("wifi reconnect attempt", self._wifi_tries)
        except Exception as e:  # noqa: BLE001
            print("wifi reconnect err:", e)

    def run(self):
        FRAME_MS = 50
        while True:
            t0 = time.ticks_ms()
            # Each pre-draw step is isolated: a transient I2C/touch/network hiccup
            # must never crash the loop and leave an illuminated-black screen.
            for step in (self._input, self._maybe_poll, self._auto_dim, self._wifi_tick):
                try:
                    step()
                except Exception as e:  # noqa: BLE001
                    print("loop step {} err: {}".format(step.__name__, e))
            try:
                self.screens[self.idx].draw()
            except Exception as e:
                self._draw_error(e)
            try:
                self.leds.tick()
            except Exception:
                pass
            try:
                self.presto.update()
            except Exception:
                pass
            elapsed = time.ticks_diff(time.ticks_ms(), t0)
            if elapsed < FRAME_MS:
                time.sleep_ms(FRAME_MS - elapsed)

    def _draw_error(self, e):
        BG = self.display.create_pen(*theme.BG)
        FG = self.display.create_pen(*theme.ERR_RED)
        self.display.set_pen(BG)
        self.display.clear()
        self.display.set_pen(FG)
        self.display.text("screen error", 16, 20, self.W, 3)
        self.display.text(str(e), 16, 80, self.W - 32, 2)
