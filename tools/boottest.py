# Bounded bring-up test: init app, draw every screen once, poll backends, report, exit.
# Run with: mpremote connect <dev> run tools/boottest.py
import time
from app.app import App

a = App()
print("WIFI", a.state.wifi_connected, "NTP", a.state.time_synced, "SENSORS", a.state.sensors_ok)

errs = []
for scr in a.screens:
    try:
        scr.draw()
        a.presto.update()
    except Exception as e:
        errs.append((scr.name, repr(e)))

# activate each screen in turn so its (gated) feed actually polls
for i in range(len(a.screens)):
    a.idx = i
    a._enter(i)
    for _ in range(8):
        a._maybe_poll()
        try:
            a.screens[a.idx].draw()
        except Exception as e:
            errs.append(("loop:" + a.screens[a.idx].name, repr(e)))
        a.leds.tick()
        a.presto.update()
        time.sleep_ms(40)

print("DGX_OK", a.state.dgx is not None, "| err:", a.state.dgx_err)
print("OPENCLAW agents:", len(a.state.openclaw_agents), "| err:", a.state.openclaw_err)
print("CRYPTO_OK", bool(a.state.crypto), "| err:", a.state.crypto_err)
sens = a.state.sensors
print("SENSORS temp={} hum={} press={} lux={}".format(
    sens.get("temp_c"), sens.get("humidity"), sens.get("pressure_hpa"), sens.get("lux")))
print("SCREEN_ERRORS:", errs if errs else "none")
print("BOOTTEST_DONE")
