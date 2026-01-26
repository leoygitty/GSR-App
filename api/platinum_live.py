# api/platinum_live.py
from http.server import BaseHTTPRequestHandler
import csv, io, time
from urllib.request import urlopen, Request

# simple in-memory cache to avoid hammering Stooq
_CACHE = {"ts": 0, "platinum_usd": None, "updated": None}
CACHE_SECONDS = 60

def _fetch_usdxpt_close():
    # Stooq quote CSV endpoint pattern (works for many tickers/pairs).
    # If your project already uses a stooq URL, reuse that same pattern here.
    url = "https://stooq.com/q/l/?s=usdxpt&f=sd2t2ohlc&h&e=csv"

    req = Request(url, headers={"User-Agent": "MetalMetric/1.0"})
    with urlopen(req, timeout=10) as r:
        text = r.read().decode("utf-8", errors="replace")

    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 2:
        raise ValueError(f"Bad CSV from Stooq: {text[:120]}")

    # header: Symbol,Date,Time,Open,High,Low,Close
    data = rows[1]
    if len(data) < 7:
        raise ValueError(f"Unexpected CSV row: {data}")

    date = data[1].strip()
    t = data[2].strip()
    close_str = data[6].strip()

    if close_str in ("", "N/D"):
        raise ValueError(f"Missing close for USDXPT: {data}")

    usdxpt = float(close_str)
    if usdxpt <= 0:
        raise ValueError(f"Non-positive USDXPT: {usdxpt}")

    # USD/XPT => invert to get USD per XPT (≈ USD per oz t platinum)
    xptusd = 1.0 / usdxpt
    updated = f"{date}T{t}Z" if t else f"{date}Z"
    return xptusd, updated


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            now = time.time()
            if _CACHE["platinum_usd"] is not None and (now - _CACHE["ts"]) < CACHE_SECONDS:
                self._send_json(200, {
                    "ok": True,
                    "platinum_usd": _CACHE["platinum_usd"],
                    "updated": _CACHE["updated"],
                    "source": "stooq usdxpt (inverted)"
                })
                return

            platinum_usd, updated = _fetch_usdxpt_close()
            _CACHE["ts"] = now
            _CACHE["platinum_usd"] = platinum_usd
            _CACHE["updated"] = updated

            self._send_json(200, {
                "ok": True,
                "platinum_usd": platinum_usd,
                "updated": updated,
                "source": "stooq usdxpt (inverted)"
            })
        except Exception as e:
            self._send_json(200, {"ok": False, "error": str(e)})

    def _send_json(self, code, obj):
        import json
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
