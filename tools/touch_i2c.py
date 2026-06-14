# Is the FT6236 touch controller alive on I2C? (non-interactive)
from presto import Presto
import time

p = Presto(full_res=True, ambient_light=False)
t = p.touch
addr = t.TOUCH_ADDR
i2c = t._i2c
print("touch addr:", hex(addr), " i2c:", i2c)
try:
    found = i2c.scan()
    print("bus scan:", [hex(a) for a in found], " addr present:", addr in found)
except Exception as e:
    print("scan err:", repr(e))


def rd(reg, n=1):
    try:
        return list(i2c.readfrom_mem(addr, reg, n))
    except Exception as e:
        return ("err", repr(e))


print("chip id  0xA3:", rd(0xA3))     # FT6236 chip id
print("firm id  0xA6:", rd(0xA6))
print("vendor   0xA8:", rd(0xA8))     # FocalTech vendor id (expect 0x11)
print("g_mode   0xA4:", rd(0xA4))     # 0=polling, 1=interrupt(trigger)
print("TD_STATUS 0x02 + pts (x6):")
for _ in range(6):
    print("   td=", rd(0x02), " p1=", rd(0x03, 4))
    time.sleep_ms(120)
print("DIAG DONE")
