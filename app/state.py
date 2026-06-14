import time


class State:
    """Shared store. Each network task writes to its slot; screens read from it."""
    def __init__(self):
        self.wifi_connected = False
        self.wifi_rssi = None
        self.time_synced = False

        # Display + rear-LED brightness. Fixed by default (no ambient auto-dim);
        # adjustable from the Settings screen and the +/- pad keys, persisted to
        # secrets.json. auto_dim re-enables the (optional) ambient light sensor.
        self.brightness = 1.0
        self.auto_dim = False

        self.dgx = None
        self.dgx_err = None
        self.dgx_ts = 0

        self.openclaw_agents = []
        self.openclaw_tasks = None
        self.openclaw_usage = None
        self.openclaw_host = None
        self.openclaw_err = None
        self.openclaw_ts = 0

        self.news = []
        self.news_err = None
        self.news_ts = 0

        self.crypto = {}
        self.crypto_err = None
        self.crypto_ts = 0

        # Uptime Kuma: live monitor status from the Prometheus /metrics endpoint.
        # kuma = [{name, up, response_ms}, ...]; kuma_roll tracks since-boot
        # reliability per monitor as [up_polls, total_polls].
        self.kuma = []
        self.kuma_err = None
        self.kuma_ts = 0
        self.kuma_roll = {}

        self.sensors = {
            "temp_c": None, "humidity": None, "pressure_hpa": None,
            "lux": None, "prox": None,
            "ax": 0.0, "ay": 0.0, "az": 0.0, "gx": 0.0, "gy": 0.0, "gz": 0.0,
        }
        self.sensors_ok = False

        self.ground_pressure_hpa = None

    def fresh(self, ts, max_age_s):
        return ts and (time.time() - ts) < max_age_s
