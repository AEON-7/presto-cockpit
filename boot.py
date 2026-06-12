import gc
import json

try:
    with open("/secrets.json") as _f:
        SECRETS = json.load(_f)
except (OSError, ValueError) as _e:
    SECRETS = None
    print("WARN: /secrets.json missing or unparseable:", _e)

gc.collect()
