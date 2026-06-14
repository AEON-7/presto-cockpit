"""A small true-random entropy pool seeded from the environment.

Every sensor read folds the low (physically noisy) bits of the IMU, barometer,
and light sensor — plus the exact microsecond of the read — into a 64-bit state,
then runs a SplitMix64 avalanche step to whiten it. Draws (coin/dice) advance the
same mixer, so every result depends on accumulated real-world noise rather than a
fixed seed. Not certified crypto-grade, but genuinely physically sourced."""
import time

_MASK64 = (1 << 64) - 1
_GOLDEN = 0x9E3779B97F4A7C15


def _mix64(z):
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9 & _MASK64
    z = (z ^ (z >> 27)) * 0x94D049BB133111EB & _MASK64
    return z ^ (z >> 31)


class EntropyPool:
    def __init__(self):
        try:
            seed = time.ticks_us()
        except Exception:
            seed = 0
        self._state = _mix64(seed & _MASK64)
        self._samples = 0
        self._buf = 0
        self._buf_bits = 0
        self.sources = "-"

    def stir(self, sensors):
        """Fold one sensor sample's noise into the pool, maximizing harvested entropy.

        Each value is scaled up so its noisy sub-unit jitter lands in integer bits,
        then the FULL 64-bit pattern is folded in (not truncated) and rotated so the
        high bits aren't lost. The IMU prefers raw (un-smoothed) readings, which carry
        far more noise than the EMA-filtered ones used for display."""
        try:
            bits = time.ticks_us() & _MASK64
        except Exception:
            bits = 0
        tags = 0
        imu = (("ax_r", "ay_r", "az_r", "gx_r", "gy_r", "gz_r")
               if sensors.get("ax_r") is not None
               else ("ax", "ay", "az", "gx", "gy", "gz"))
        for k in imu:                                            # IMU thermal/electronic noise (amplified)
            v = sensors.get(k)
            if v is not None:
                iv = int(v * 1000000.0) & _MASK64
                bits = (bits ^ iv) & _MASK64
                bits = ((bits << 13) | (bits >> 51)) & _MASK64
                tags |= 1
        for k, sc in (("temp_c", 1e7), ("humidity", 1e6), ("pressure_hpa", 1e6)):
            v = sensors.get(k)                                   # barometer LSB jitter (full width)
            if v is not None:
                iv = int(v * sc) & _MASK64
                bits = (bits ^ iv) & _MASK64
                bits = ((bits << 11) | (bits >> 53)) & _MASK64
                tags |= 2
        for k in ("lux", "prox"):                                # light/proximity noise
            v = sensors.get(k)
            if v is not None:
                iv = int(v * 1000.0) & _MASK64
                bits = (bits ^ iv) & _MASK64
                bits = ((bits << 7) | (bits >> 57)) & _MASK64
                tags |= 4
        self._state = _mix64((self._state ^ bits) & _MASK64)
        self._samples += 1
        if tags:
            parts = []
            if tags & 1:
                parts.append("IMU")
            if tags & 2:
                parts.append("baro")
            if tags & 4:
                parts.append("light")
            self.sources = "+".join(parts)

    def _next64(self):
        self._state = (self._state + _GOLDEN) & _MASK64
        return _mix64(self._state)

    def bits(self, n):
        out = 0
        got = 0
        while got < n:
            if self._buf_bits == 0:
                self._buf = self._next64()
                self._buf_bits = 64
            take = n - got
            if take > self._buf_bits:
                take = self._buf_bits
            out = (out << take) | (self._buf & ((1 << take) - 1))
            self._buf >>= take
            self._buf_bits -= take
            got += take
        return out

    def randbelow(self, k):
        """Unbiased integer in [0, k) via rejection sampling.

        (MicroPython's int has no .bit_length(), so count bits by hand.)"""
        if k <= 1:
            return 0
        nbits = 0
        x = k - 1
        while x:
            nbits += 1
            x >>= 1
        while True:
            r = self.bits(nbits)
            if r < k:
                return r

    def ready(self):
        return self._samples >= 8

    def fill(self):
        f = self._samples / 64.0
        return 1.0 if f > 1.0 else f
