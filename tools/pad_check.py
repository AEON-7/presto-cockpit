# Is the Qw/ST nav pad present on the sensor I2C bus? (non-interactive)
from presto import Presto
p = Presto(full_res=True, ambient_light=False)
from app.hw.sensors import Sensors
from app.hw.pad import Pad

s = Sensors()
i2c = s.i2c
if i2c is None:
    print("sensor i2c is None")
else:
    found = i2c.scan()
    print("sensor/pad bus:", i2c)
    print("scan:", [hex(a) for a in found], " pad@0x21 present:", 0x21 in found)
pad = Pad(i2c)
print("pad.ok:", pad.ok)
try:
    print("read_buttons:", pad.pad.read_buttons() if pad.ok else None)
except Exception as e:
    print("read err:", repr(e))
