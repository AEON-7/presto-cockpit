class Pad:
    """Qw/ST Pad wrapper that emits edge-triggered events.
    Pass the same I2C bus already shared with the sensor stick."""

    KEYS = ("U", "D", "L", "R", "A", "B", "X", "Y", "+", "-")

    def __init__(self, i2c, address=0x21):
        self.ok = False
        self.pad = None
        self._prev = {k: False for k in self.KEYS}
        if i2c is None:
            return
        try:
            from qwstpad import QwSTPad
            self.pad = QwSTPad(i2c, address, show_address=False)
            self.ok = True
        except Exception as e:
            print("pad: init failed:", e)

    def poll(self):
        """Returns list of just-pressed key names since last poll."""
        if not self.ok:
            return []
        try:
            state = self.pad.read_buttons()
        except Exception:
            return []
        pressed = []
        for k in self.KEYS:
            now = bool(state.get(k))
            if now and not self._prev[k]:
                pressed.append(k)
            self._prev[k] = now
        return pressed

    def held(self, key):
        return self._prev.get(key, False)
