from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone
import json
import urllib.request
import csv
import io

try:
    from ._utils import send_json
except Exception:
    from api._utils import send_json


# Stooq CSV quote endpoint (no API key required)
# Example format used broadly: https://stooq.com/q/l/?s=%1&f=sd2t2ohlcv&h&e=csv
STOOQ_URL_TPL = "https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlc&h&e=csv"

# Map your old Yahoo symbols to Stooq symbols (keeps ?symbols=GC=F,SI=F compatible)
SYMBOL_MAP = {
    "GC=F": "gc.f",  # Gold futures
    "SI=F": "si.f",  # Silver futures
    "gc.f": "gc.f",
    "si.f": "si.f",
}


def _http_get_text(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (MetalMetric; +https://metalmetric.com)",
            "Accept": "text/csv,text/plain,application/json;q=0.9,*/*;q=0.8",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    # Stooq uses UTF-8
    return raw.decode("utf-8", errors="replace")


def _fetch_stooq_last(symbol: str):
    """
    Returns (price_float, date_str, time_str) from Stooq CSV quote.
    Expected CSV header includes: Symbol,Date,Time,Open,High,Low,Close
    """
    url = STOOQ_URL_TPL.format(symbol=symbol)
    text = _http_get_text(url, timeout=15)

    # Stooq returns CSV with header + one row for quote endpoints
    # Guard: if we accidentally got HTML (maintenance/ban), fail cleanly
    if "<html" in text.lower():
        raise RuntimeError("Stooq returned HTML instead of CSV.")

    f = io.StringIO(text)
    reader = csv.DictReader(f)

    row = next(reader, None)
    if not row:
        raise RuntimeError("Stooq CSV missing data row.")

    # Normalize keys (some environments may alter casing)
    norm = { (k or "").strip().lower(): (v or "").strip() for k, v in row.items() }

    close_raw = norm.get("close") or norm.get("c")
    if not close_raw or close_raw.upper() in ("N/A", "NA", "N/D", "-"):
        raise RuntimeError("Stooq CSV missing close price.")

    price = float(close_raw)

    d = norm.get("date") or norm.get("d") or ""
    t = norm.get("time") or norm.get("t") or ""

    return price, d, t


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            qs = parse_qs(urlparse(self.path).query)

            # Keep compatibility with your previous interface:
            # /api/spot?symbols=GC=F,SI=F
            symbols_raw = (qs.get("symbols", ["GC=F,SI=F"])[0] or "GC=F,SI=F").strip()
            requested = [s.strip() for s in symbols_raw.split(",") if s.strip()]

            # Translate symbols to Stooq equivalents (only supports gold/silver for now)
            stooq_syms = []
            unknown = []
            for s in requested:
                key = s.strip()
                mapped = SYMBOL_MAP.get(key) or SYMBOL_MAP.get(key.lower()) or SYMBOL_MAP.get(key.upper())
                if mapped:
                    stooq_syms.append(mapped)
                else:
                    unknown.append(key)

            # Ensure we fetch at least gold + silver by default
            if not stooq_syms:
                stooq_syms = ["gc.f", "si.f"]

            # Deduplicate while keeping order
            seen = set()
            stooq_syms = [x for x in stooq_syms if not (x in seen or seen.add(x))]

            # Fetch prices
            prices = {}
            market_meta = {}
            for sym in stooq_syms:
                px, d, t = _fetch_stooq_last(sym)
                prices[sym] = px
                market_meta[sym] = {"date": d, "time": t}

            gold_px = prices.get("gc.f")
            silver_px = prices.get("si.f")

            if gold_px is None or silver_px is None:
                return send_json(self, 502, {
                    "ok": False,
                    "error": "Price source unavailable (missing gold or silver).",
                    "debug": {
                        "requested": requested,
                        "mapped": stooq_syms,
                        "unknown": unknown,
                        "have_gc_f": gold_px is not None,
                        "have_si_f": silver_px is not None,
                    }
                })

            if silver_px == 0:
                return send_json(self, 502, {"ok": False, "error": "Invalid silver price (0)."})

            gsr = gold_px / silver_px

            now_utc = datetime.now(timezone.utc).isoformat()
            today_utc = datetime.now(timezone.utc).date().isoformat()

            # Optional: include the market timestamp Stooq returned (if present)
            market_date = market_meta.get("gc.f", {}).get("date") or market_meta.get("si.f", {}).get("date") or ""
            market_time = market_meta.get("gc.f", {}).get("time") or market_meta.get("si.f", {}).get("time") or ""

            return send_json(self, 200, {
                "ok": True,
                "date": today_utc,
                "gold_usd": float(gold_px),
                "silver_usd": float(silver_px),
                "gsr": float(gsr),
                "fetched_at_utc": now_utc,
                "source": "spot_stooq",
                "market": {
                    "date": market_date,
                    "time": market_time,
                    "symbols": {"gold": "gc.f", "silver": "si.f"}
                },
                "debug": {
                    "requested": requested,
                    "mapped": stooq_syms,
                    "unknown": unknown
                }
            })

        except Exception as e:
            # Preserve your current behavior: surface upstream HTTP errors cleanly
            return send_json(self, 502, {"ok": False, "error": str(e)})

    def log_message(self, format, *args):
        return
