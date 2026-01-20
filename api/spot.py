from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone
import json
import urllib.request

try:
    from ._utils import send_json
except Exception:
    from api._utils import send_json


YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote?symbols=GC=F,SI=F"


def _fetch_yahoo_quotes():
    req = urllib.request.Request(
        YAHOO_QUOTE_URL,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8")
        data = json.loads(raw)

    results = (data.get("quoteResponse") or {}).get("result") or []
    return {r.get("symbol"): r for r in results if r.get("symbol")}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            # Optional: allow ?symbols=GC=F,SI=F (defaults if not provided)
            qs = parse_qs(urlparse(self.path).query)
            symbols = (qs.get("symbols", ["GC=F,SI=F"])[0] or "GC=F,SI=F").strip()
            url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbols}"

            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json",
                },
                method="GET",
            )

            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)

            results = (data.get("quoteResponse") or {}).get("result") or []
            by_symbol = {r.get("symbol"): r for r in results if r.get("symbol")}

            gold = by_symbol.get("GC=F") or {}
            silver = by_symbol.get("SI=F") or {}

            gold_px = gold.get("regularMarketPrice")
            silver_px = silver.get("regularMarketPrice")

            if gold_px is None or silver_px is None:
                return send_json(self, 502, {
                    "ok": False,
                    "error": "Price source unavailable (missing regularMarketPrice).",
                    "debug": {"has_gold": bool(gold), "has_silver": bool(silver)}
                })

            gold_px = float(gold_px)
            silver_px = float(silver_px)
            if silver_px == 0:
                return send_json(self, 502, {"ok": False, "error": "Invalid silver price (0)."})

            gsr = gold_px / silver_px

            now_utc = datetime.now(timezone.utc).isoformat()
            today_utc = datetime.now(timezone.utc).date().isoformat()

            return send_json(self, 200, {
                "ok": True,
                "date": today_utc,
                "gold_usd": gold_px,
                "silver_usd": silver_px,
                "gsr": gsr,
                "fetched_at_utc": now_utc,
                "source": "spot_yahoo"
            })

        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": str(e)})

    def log_message(self, format, *args):
        return
