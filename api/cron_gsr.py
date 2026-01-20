from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone
import json
import urllib.request
import os

try:
    from ._utils import db_connect, send_json
except Exception:
    from api._utils import db_connect, send_json


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
    by_symbol = {r.get("symbol"): r for r in results if r.get("symbol")}
    return by_symbol


def _is_authorized(handler_obj, qs):
    # Allow Vercel Cron header
    if (handler_obj.headers.get("x-vercel-cron") or "").strip() == "1":
        return True

    cron_secret = (os.getenv("CRON_SECRET") or "").strip()
    if not cron_secret:
        return False

    provided = (qs.get("secret", [""])[0] or "").strip()

    auth_header = (handler_obj.headers.get("Authorization") or "").strip()
    bearer = ""
    if auth_header.lower().startswith("bearer "):
        bearer = auth_header.split(" ", 1)[1].strip()

    return (provided == cron_secret) or (bearer == cron_secret)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            qs = parse_qs(urlparse(self.path).query)

            if not _is_authorized(self, qs):
                return send_json(self, 401, {
                    "ok": False,
                    "error": "Unauthorized",
                    "hint": "Vercel cron should pass x-vercel-cron: 1. For manual calls, use Authorization: Bearer <CRON_SECRET> or ?secret=<CRON_SECRET>."
                })

            by_symbol = _fetch_yahoo_quotes()
            gold = by_symbol.get("GC=F") or {}
            silver = by_symbol.get("SI=F") or {}

            gold_px = gold.get("regularMarketPrice")
            silver_px = silver.get("regularMarketPrice")

            if gold_px is None or silver_px is None:
                return send_json(self, 502, {
                    "ok": False,
                    "error": "Price source unavailable (missing regularMarketPrice).",
                    "debug": {
                        "has_gold": bool(gold),
                        "has_silver": bool(silver),
                        "symbols": list(by_symbol.keys()),
                    }
                })

            gold_px = float(gold_px)
            silver_px = float(silver_px)

            if silver_px == 0:
                return send_json(self, 502, {"ok": False, "error": "Invalid silver price (0)."})

            gsr = gold_px / silver_px

            now_utc = datetime.now(timezone.utc).isoformat()
            today_utc = datetime.now(timezone.utc).date().isoformat()

            conn = db_connect()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO gsr_daily (d, gold_usd, silver_usd, gsr, fetched_at_utc, source)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (d) DO UPDATE
                      SET gold_usd = EXCLUDED.gold_usd,
                          silver_usd = EXCLUDED.silver_usd,
                          gsr = EXCLUDED.gsr,
                          fetched_at_utc = EXCLUDED.fetched_at_utc,
                          source = EXCLUDED.source;
                    """,
                    (today_utc, gold_px, silver_px, gsr, now_utc, "cron_hourly_yahoo")
                )
                conn.commit()
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

            return send_json(self, 200, {
                "ok": True,
                "date": today_utc,
                "gold_usd": gold_px,
                "silver_usd": silver_px,
                "gsr": gsr,
                "fetched_at_utc": now_utc,
                "source": "cron_hourly_yahoo"
            })

        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": str(e)})

    def log_message(self, format, *args):
        return
