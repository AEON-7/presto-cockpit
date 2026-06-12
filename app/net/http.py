try:
    import requests
except ImportError:
    import urequests as requests


def get_json(url, timeout=4, headers=None):
    r = None
    try:
        r = requests.get(url, timeout=timeout, headers=headers or {})
        if r.status_code != 200:
            return None, "http {}".format(r.status_code)
        return r.json(), None
    except Exception as e:
        return None, str(e)
    finally:
        if r is not None:
            try:
                r.close()
            except Exception:
                pass


def get_text(url, timeout=4, headers=None):
    r = None
    try:
        r = requests.get(url, timeout=timeout, headers=headers or {})
        if r.status_code != 200:
            return None, "http {}".format(r.status_code)
        return r.text, None
    except Exception as e:
        return None, str(e)
    finally:
        if r is not None:
            try:
                r.close()
            except Exception:
                pass
