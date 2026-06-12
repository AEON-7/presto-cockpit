#!/usr/bin/env bash
# Reads .env and writes secrets.json with proper UTF-8.
# Parses .env in Python (NOT bash `source`) so passwords with $, `, ", \ etc.
# are never shell-evaluated.
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] || { echo "no .env (copy .env.example to .env first)"; exit 1; }

python3 - .env <<'PY'
import json, sys

def parse_env(path):
    d = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            s = line.strip()
            if not s or s.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if v[:1] == '"':
                try:
                    v = json.loads(v)            # JSON-decode (handles escapes)
                except ValueError:
                    v = v[1:-1] if v[-1:] == '"' else v[1:]
            elif v[:1] == "'":
                v = v[1:-1] if v[-1:] == "'" else v[1:]
            d[k] = v
    return d

e = parse_env(sys.argv[1])
def g(k, default=None): return e.get(k, default)

def fl(k, default):
    try:
        return float(e.get(k, default))
    except (TypeError, ValueError):
        return float(default)

data = {
    "wifi": {
        "ssid": g("WIFI_SSID", ""),
        "password": g("WIFI_PASSWORD", ""),
        "country": g("WIFI_COUNTRY", "US"),
    },
    "dgx": {
        "url": g("DGX_URL", ""),
        "poll_interval_s": fl("DGX_POLL_S", 1.0),
    },
    "openclaw": {
        "url": g("OPENCLAW_URL", ""),
        "bearer": g("OPENCLAW_BEARER", ""),
        "poll_interval_s": fl("OPENCLAW_POLL_S", 2.0),
    },
    "crypto": {
        "ids": [c.strip() for c in g("CRYPTO_IDS", "bitcoin,ethereum,monero,solana").split(",") if c.strip()],
        "vs": g("CRYPTO_VS", "usd"),
        "poll_interval_s": fl("CRYPTO_POLL_S", 30),
    },
    "altitude": {
        "sea_level_hpa": fl("SEA_LEVEL_HPA", 1013.25),
    },
    "lights": {
        "default_brightness": fl("LED_BRIGHTNESS", 0.6),
        "auto_dim_from_ambient": str(g("LED_AUTO_DIM", "true")).lower() in ("1", "true", "yes"),
    },
}
with open("secrets.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print("wrote secrets.json (ssid={!r}, wifi_pwd={})".format(
    data["wifi"]["ssid"], "set" if data["wifi"]["password"] else "EMPTY"))
PY
