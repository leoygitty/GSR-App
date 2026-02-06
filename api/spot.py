from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone
import os
import json
import time
import urllib.request
import urllib.error

try:
    from ._utils import send_json
except Exception:
    from api._utils import send_json


# GoldPrice.org spot for XAU/XAG (no key)
GOLDPRICE_URL = "https://data-asg.goldprice.org/dbXRates/USD"

# MetalPriceAPI spot for XPT (key required)
METALPRICEAPI_URL = "https://api.metalpriceapi.com/v1/latest"

# Simple in-memory cache to avoid burning your 100-request free tier
CACHE_TTL_SECONDS = 60
_CACHE = {"ts": 0.0, "payload": None}


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _http_get_json(url: str, headers: dict, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def _fetch_goldprice_gold_silver():
    """
    Returns (gold_usd, silver_usd, gsr) from GoldPrice.org JSON:
      items[0].xauPrice, items[0].xagPrice in USD
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (MetalMetric; +https://metalmetric.com)",
        "Accept": "application/json",
        "Referer": "https://goldprice.org/",
        "Origin": "https://goldprice.org",
    }

    data = _http_get_json(GOLDPRICE_URL, headers=headers, timeout=15)
    items = data.get("items") or []
    if not items:
        raise ValueError("GoldPrice response missing items[]")

    it = items[0] or {}
    gold = float(it.get("xauPrice"))
    silver = float(it.get("xagPrice"))

    if gold <= 0 or silver <= 0:
        raise ValueError(f"Non-positive gold/silver: gold={gold}, silver={silver}")

    return gold, silver, (gold / silver)


def _fetch_metalpriceapi_platinum():
    """
    Returns platinum spot USD/oz (XPT) using MetalPriceAPI.
    We request base=USD&currencies=XPT and compute USD/oz.

    MetalPriceAPI may return either:
      - rates["USDXPT"]  (direct USD per 1 XPT oz), OR
      - rates["XPT"]     (XPT per 1 USD), then USD/oz = 1 / rate
    """
    api_key = (os.environ.get("METALPRICEAPI_KEY") or "").strip()
    if not api_key:
        raise ValueError("Missing METALPRICEAPI_KEY environment variable")

    url = f"{METALPRICEAPI_URL}?api_key={api_key}&base=USD&currencies=XPT"
    headers = {
        "User-Agent": "Mozilla/5.0 (MetalMetric; +https://metalmetric.com)",
        "Accept": "application/json",
    }

    data = _http_get_json(url, headers=headers, timeout=15)
    rates = data.get("rates") or {}

    direct = rates.get("USDXPT")
    if direct not in (None, "", 0, "0"):
        px = float(direct)
        if px <= 0:
            raise ValueError(f"Invalid USDXPT={direct}")
        return px

    inv = rates.get("XPT")
    if inv in (None, "", 0, "0"):
        raise ValueError(f"MetalPriceAPI missing XPT rate in response: {rates}")

    inv = float(inv)
    if inv <= 0:
        raise ValueError(f"Invalid XPT rate={inv}")
    return 1.0 / inv


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            qs = parse_qs(urlparse(self.path).query)
            force = (qs.get("force", ["0"])[0] or "0").strip().lower() in ("1", "true", "yes", "on")

            # Cache (protects your 100-request tier)
            now = time.time()
            if (not force) and _CACHE["payload"] and (now - _CACHE["ts"] < CACHE_TTL_SECONDS):
                return send_json(self, 200, _CACHE["payload"])

            # Gold & silver are REQUIRED
            gold_usd, silver_usd, gsr = _fetch_goldprice_gold_silver()

            # Platinum is OPTIONAL (never break the endpoint)
            platinum_usd = None
            platinum_error = None
            try:
                platinum_usd = float(_fetch_metalpriceapi_platinum())
            except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as e:
                platinum_error = str(e)
            except Exception as e:
                platinum_error = str(e)

            payload = {
                "ok": True,
                "date": datetime.now(timezone.utc).date().isoformat(),
                "gold_usd": float(gold_usd),
                "silver_usd": float(silver_usd),
                "platinum_usd": platinum_usd,  # may be None
                "gsr": float(gsr),
                "fetched_at_utc": _utc_now_iso(),
                "source": "spot_mixed",
                "sources": {
                    "gold_silver": "spot_goldprice",
                    "platinum": "spot_metalpriceapi",
                },
                "cache": {
                    "ttl_seconds": CACHE_TTL_SECONDS,
                    "forced": bool(force),
                }
            }

            # Only include this key when something went wrong (keeps response clean)
            if platinum_error:
                payload["platinum_error"] = platinum_error

            _CACHE["ts"] = now
            _CACHE["payload"] = payload
            return send_json(self, 200, payload)

        except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as e:
            # Keep this as 502 because it means gold/silver failed (critical)
            return send_json(self, 502, {"ok": False, "error": str(e)})
        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": str(e)})

    def log_message(self, format, *args):
        return
