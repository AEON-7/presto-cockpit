"""Uptime Kuma — live monitor status from its Prometheus /metrics endpoint.

Kuma's main dashboard is socket.io/authed, so we scrape /metrics instead. It is
protected by a Kuma API key, sent as the HTTP Basic-auth password (username is
ignored). /metrics is point-in-time (current up/down + response time); historical
uptime % is accumulated on-device by the caller."""
from app.net.http import get_text

try:
    import ubinascii as _b64
except ImportError:
    import binascii as _b64


def _auth_header(api_key):
    if not api_key:
        return {}
    tok = _b64.b2a_base64((":" + api_key).encode()).decode().strip()
    return {"Authorization": "Basic " + tok}


def _value(line):
    try:
        return float(line.rsplit(" ", 1)[1])
    except Exception:
        return None


def _monitor_name(line):
    i = line.find('monitor_name="')
    if i < 0:
        return None
    i += 14  # len('monitor_name="')
    j = line.find('"', i)
    return line[i:j] if j > i else None


def fetch(url, api_key=None, timeout=6):
    """Returns (monitors, err). monitors = [{name, up, response_ms}], where up is
    1 (up) / 0 (down) / 2 (pending) / 3 (maintenance), sorted down-first then name."""
    text, err = get_text(url, timeout=timeout, headers=_auth_header(api_key))
    if err:
        return None, err
    status = {}
    resp = {}
    for line in text.split("\n"):
        if line.startswith("monitor_status{"):
            n = _monitor_name(line)
            v = _value(line)
            if n is not None and v is not None:
                status[n] = int(v)
        elif line.startswith("monitor_response_time{"):
            n = _monitor_name(line)
            v = _value(line)
            if n is not None and v is not None and v >= 0:   # Kuma reports -1 for "no value"
                resp[n] = v
    if not status:
        return None, "no monitors"
    out = [{"name": n, "up": status[n], "response_ms": resp.get(n)} for n in status]
    out.sort(key=lambda m: (m["up"] == 1, m["name"]))   # down/pending first
    return out, None
