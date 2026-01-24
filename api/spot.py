from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone
import json
import urllib.request
import urllib.error

try:
    from ._utils import send_json
except Exception:
    from api._utils import send_json


# GoldPrice.org JSON endpoint (no API key required)
# Returns JSON with items[0].xauPrice and items[0].xagPrice in USD
GOLDPRICE_URL = "https://data-asg.goldprice.org/dbXRates/USD"


def _http_get_json(url: str, timeout: int = 15) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (MetalMetric; +https://metalmetric.com)",
            "Accept": "application/json,text/plain,*/*",
            # These two headers help with some CDN/anti-bot configs
            "Referer": "https://goldprice.org/",
            "Origin": "https://goldprice.org",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def _fetch_goldprice_spot():
    """
    Returns (gold_usd, silver_usd) floats from GOLDPRICE_URL.
    Expected JSON: { "items": [ { "xauPrice": <num>, "xagPrice": <num>, ... } ], ... }
    """
    data = _http_get_json(GOLDPRICE_URL, timeout=15)
    items = data.get("items") or []
    if not items:
        raise ValueError("GoldPrice response missing items[]")

    it = items[0] or {}
    gold = it.get("xauPrice")
    silver = it.get("xagPrice")

    if gold is None or silver is None:
        raise ValueError(f"Missing xauPrice/xagPrice in response: {it}")

    gold = float(gold)
    silver = float(silver)

    if gold <= 0 or silver <= 0:
        raise ValueError(f"Non-positive prices: gold={gold}, silver={silver}")

    return gold, silver


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            # Optional: allow a timeout override for debugging (seconds)
            qs = parse_qs(urlparse(self.path).query)
            timeout_raw = (qs.get("timeout", ["15"])[0] or "15").strip()
            try:
                timeout = int(timeout_raw)
            except Exception:
                timeout = 15
            timeout = max(5, min(timeout, 30))

            # Fetch true spot
            gold_usd, silver_usd = _fetch_goldprice_spot()

            gsr = gold_usd / silver_usd

            now_utc = datetime.now(timezone.utc).isoformat()
            today_utc = datetime.now(timezone.utc).date().isoformat()

            return send_json(self, 200, {
                "ok": True,
                "date": today_utc,
                "gold_usd": float(gold_usd),
                "silver_usd": float(silver_usd),
                "gsr": float(gsr),
                "fetched_at_utc": now_utc,
                "source": "spot_goldprice",
            })

        except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as e:
            return send_json(self, 502, {
                "ok": False,
                "error": str(e),
                "hint": "Upstream spot source blocked/failed. Try again or use Manual mode.",
                "source": "spot_goldprice"
            })
        except Exception as e:
            return send_json(self, 502, {"ok": False, "error": str(e), "source": "spot_goldprice"})

    def log_message(self, format, *args):
        return
