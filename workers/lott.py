"""The Lott's public results API: one small client shared by the workers (stdlib only, no keys)."""
import datetime as dt
import json
import time
import urllib.error
import urllib.request

BASE = "https://data.api.thelott.com/sales/vmax/web/data/lotto/"
COMPANY = "Tattersalls"          # Victoria's licensee; numbers are the same nationally
MAX_DAYS = 89                    # the date-range search refuses ranges over 90 days


def post(path, body, tries=4):
    """POST JSON, retrying transient failures with backoff. Raises on an API-reported error."""
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(), {"content-type": "application/json"})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            break
        except (urllib.error.URLError, TimeoutError) as exc:
            if i == tries - 1:
                raise
            time.sleep(2 ** (i + 1))
    if data.get("Success") is False:
        raise RuntimeError(f"{path}: {data.get('ErrorInfo')}")
    return data


def windows(start, end, days=MAX_DAYS):
    """Consecutive [a, b] date windows covering start..end, each at most `days` long."""
    a = start
    while a <= end:
        b = min(a + dt.timedelta(days=days), end)
        yield a, b
        a = b + dt.timedelta(days=1)


def draws_between(product, start, end):
    """Every draw of `product` with a draw date in [start, end] (one request)."""
    body = {"CompanyFilter": [COMPANY], "ProductFilter": [product],
            "DateStart": f"{start.isoformat()}T00:00:00", "DateEnd": f"{end.isoformat()}T23:59:59"}
    return post("results/search/daterange", body).get("Draws") or []
