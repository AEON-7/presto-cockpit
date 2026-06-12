"""Lists images in /images and decodes them with jpegdec.
LED sync uses presto.auto_ambient_leds(True) so we don't have to read pixels."""
import os


def list_images():
    out = []
    try:
        for name in os.listdir("/images"):
            if name.startswith("."):
                continue
            low = name.lower()
            if low.endswith((".jpg", ".jpeg")):
                out.append("/images/" + name)
    except OSError:
        pass
    return sorted(out)
