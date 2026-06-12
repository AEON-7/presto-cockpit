from app.net.http import get_json


def fetch(url):
    return get_json(url, timeout=4)


def container(vitals_url, cid):
    base = vitals_url.rsplit("/", 1)[0]   # strip trailing /vitals
    return get_json(base + "/container/" + cid, timeout=6)
