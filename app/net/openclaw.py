"""Consumes the OpenClaw LAN shim (runs on the gateway box).
The gateway itself only speaks RPC/WS + a locked HTTP surface, so the shim
shells out to the `openclaw` CLI and serves digested JSON here."""
from app.net.http import get_json


def fetch(url, bearer=None):
    # Shim is LAN+ufw scoped and needs no bearer; header sent only if present.
    headers = {"Authorization": "Bearer " + bearer} if bearer else None
    data, err = get_json(url, timeout=6, headers=headers)
    if err:
        return None, err
    return data, None


def agent_detail(agents_url, aid, bearer=None):
    base = agents_url.rsplit("/", 1)[0]   # strip trailing /agents
    headers = {"Authorization": "Bearer " + bearer} if bearer else None
    return get_json(base + "/agent?id=" + aid, timeout=6, headers=headers)
