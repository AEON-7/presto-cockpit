from app.net.http import get_json


URL = ("https://api.coingecko.com/api/v3/simple/price"
       "?ids={ids}&vs_currencies={vs}&include_24hr_change=true")

# CoinGecko's Cloudflare 403s requests with no User-Agent (MicroPython's default).
HEADERS = {"User-Agent": "Mozilla/5.0 (presto-cockpit)", "Accept": "application/json"}


def fetch(ids, vs):
    url = URL.format(ids=",".join(ids), vs=vs)
    data, err = get_json(url, timeout=6, headers=HEADERS)
    if err:
        return {}, err
    out = {}
    for coin in ids:
        row = data.get(coin, {})
        out[coin] = {
            "price": row.get(vs),
            "change_24h": row.get(vs + "_24h_change"),
        }
    return out, None
