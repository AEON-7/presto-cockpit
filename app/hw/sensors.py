import machine
import time


class Sensors:
    """Multi-Sensor Stick wrapper. BME280 + LTR559 + LSM6DS3 on the Qw/ST bus.
    Gracefully no-ops if the stick isn't attached."""

    def __init__(self):
        self.ok_bme = self.ok_ltr = self.ok_imu = False
        self.bme = self.ltr = self.imu = None
        try:
            self.i2c = machine.I2C()
        except Exception:
            self.i2c = None
            return

        try:
            from breakout_bme280 import BreakoutBME280
            self.bme = BreakoutBME280(self.i2c)
            self.ok_bme = True
        except Exception as e:
            print("sensors: BME280 init failed:", e)

        try:
            from breakout_ltr559 import BreakoutLTR559
            self.ltr = BreakoutLTR559(self.i2c)
            self.ok_ltr = True
        except Exception as e:
            print("sensors: LTR559 init failed:", e)

        try:
            from lsm6ds3 import LSM6DS3, NORMAL_MODE_104HZ
            self.imu = LSM6DS3(self.i2c, mode=NORMAL_MODE_104HZ)
            self.ok_imu = True
        except Exception as e:
            print("sensors: LSM6DS3 init failed:", e)

        self._smooth = None

    def read(self, dst):
        """Refresh dst dict in place with current readings."""
        if self.ok_bme:
            try:
                t, p, h = self.bme.read()
                dst["temp_c"] = t
                dst["pressure_hpa"] = p / 100.0
                dst["humidity"] = h
            except Exception:
                pass
        if self.ok_ltr:
            try:
                r = self.ltr.get_reading()
                if r:
                    dst["lux"] = r[0] if isinstance(r, (tuple, list)) else getattr(r, "lux", None)
                    dst["prox"] = r[1] if isinstance(r, (tuple, list)) and len(r) > 1 else getattr(r, "proximity", None)
            except Exception:
                pass
        if self.ok_imu:
            try:
                ax, ay, az, gx, gy, gz = self.imu.get_readings()
                if self._smooth is None:
                    self._smooth = [ax, ay, az, gx, gy, gz]
                a = 0.2
                self._smooth = [a * v + (1 - a) * s for v, s in zip((ax, ay, az, gx, gy, gz), self._smooth)]
                dst["ax"], dst["ay"], dst["az"] = self._smooth[0:3]
                dst["gx"], dst["gy"], dst["gz"] = self._smooth[3:6]
            except Exception:
                pass
        return self.ok_bme or self.ok_ltr or self.ok_imu

    @staticmethod
    def altitude_m(p_hpa, sea_level_hpa=1013.25):
        if not p_hpa:
            return None
        return 44330.0 * (1.0 - (p_hpa / sea_level_hpa) ** 0.1903)

    @staticmethod
    def pitch_roll(ax, ay, az):
        import math
        roll = math.atan2(ay, az)
        pitch = math.atan2(-ax, (ay * ay + az * az) ** 0.5)
        return pitch, roll
