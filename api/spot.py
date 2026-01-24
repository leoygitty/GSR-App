from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone
import urllib.request
import csv
import io

try:
    from ._utils import send_json
except Exception:
    from api._utils import send_json


# Stooq CSV quote endpoint (no API key required)
STOOQ_URL_TPL = "https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlc&h&e=csv"

# Keep compatibility with your old interface (?symbols=GC=F,SI=F)
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
    return raw.decode("utf-8", errors="replace")


def _fetch_stooq_last(symbol: str):
    """
    Returns (price_float, date_str, time_str) from Stooq CSV quote.
    CSV header includes: Symbol,Date,Time,Open,High,Low,Close
    """
    url = STOOQ_URL_TPL.format(symbol=symbol)
    text = _http_get_text(url, timeout=15)

    if "<html" in text.lower():
        raise RuntimeError("Stooq returned HTML instead of CSV.")

    f = io.StringIO(text)
    reader = csv.DictReader(f)
    row = next(reader, None)
    if not row:
        raise RuntimeError("Stooq CSV missing data row.")

    norm = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}

    close_raw = norm.get("close") or norm.get("c")
    if not close_raw or close_raw.upper() in ("N/A", "NA", "N/D", "-"):
        raise RuntimeError("Stooq CSV missing close price.")

    price = float(close_raw)
    d = norm.get("date") or norm.get("d") or ""
    t = norm.get("time") or norm.get("t") or ""
    return price, d, t


def _normalize_price(metal: str, px: float):
    """
    Stooq futures sometimes return different scaling.
    We apply conservative heuristics:
    - Silver sometimes returns in cents (e.g., 10133.3 => $101.333). If very large, divide by 100.
    - Gold should be in dollars; only downscale if it’s absurdly large.
    """
    if px is None:
        return None

    px = float(px)

    if metal == "silver":
        # If silver is > 500, it is almost certainly cents-based in this feed.
        # This keeps normal silver prices (e.g., 20-300) untouched.
        if px > 500:
            return px / 100.0
        return px

    if metal == "gold":
        # Defensive: if gold is absurdly large, it's probably scaled.
        if px > 100000:
            return px / 100.0
        return px

    return px


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            qs = parse_qs(urlparse(self.path).query)
            symbols_raw = (qs.get("symbols", ["GC=F,SI=F"])[0] or "GC=F,SI=F").strip()
            requested = [s.strip() for s in symbols_raw.split(",") if s.strip()]

            stooq_syms = []
            unknown = []
            for s in requested:
                key = s.strip()
                mapped = SYMBOL_MAP.get(key) or SYMBOL_MAP.get(key.lower()) or SYMBOL_MAP.get(key.upper())
                if mapped:
                    stooq_syms.append(mapped)
                else:
                    unknown.append(key)

            if not stooq_syms:
                stooq_syms = ["gc.f", "si.f"]

            seen = set()
            stooq_syms = [x for x in stooq_syms if not (x in seen or seen.add(x))]

            prices_raw = {}
            market_meta = {}
            for sym in stooq_syms:
                px, d, t = _fetch_stooq_last(sym)
                prices_raw[sym] = px
                market_meta[sym] = {"date": d, "time": t}

            gold_raw = prices_raw.get("gc.f")
            silver_raw = prices_raw.get("si.f")

            if gold_raw is None or silver_raw is None:
                return send_json(self, 502, {
                    "ok": False,
                    "error": "Price source unavailable (missing gold or silver).",
                    "debug": {
                        "requested": requested,
                        "mapped": stooq_syms,
                        "unknown": unknown,
                        "have_gc_f": gold_raw is not None,
                        "have_si_f": silver_raw is not None,
                    }
                })

            gold_px = _normalize_price("gold", gold_raw)
            silver_px = _normalize_price("silver", silver_raw)

            if silver_px == 0:
                return send_json(self, 502, {"ok": False, "error": "Invalid silver price (0)."})

            gsr = gold_px / silver_px

            now_utc = datetime.now(timezone.utc).isoformat()
            today_utc = datetime.now(timezone.utc).date().isoformat()

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
                # Keep debug so we can verify scaling in prod
                "debug": {
                    "requested": requested,
                    "mapped": stooq_syms,
                    "unknown": unknown,
                    "raw": {"gold": gold_raw, "silver": silver_raw},
                    "normalized": {"gold": gold_px, "silver": silver_px}
                }
            })

        except Exception as e:
            return send_json(self, 502, {"ok": False, "error": str(e)})

    def log_message(self, format, *args):
        return
