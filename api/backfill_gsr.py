from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone
import csv
import os

from ._utils import db_connect, send_json


DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
GOLD_CSV = os.path.join(DATA_DIR, "xauusd.csv")
SILVER_CSV = os.path.join(DATA_DIR, "xagusd.csv")


def _safe_float(x: str):
    try:
        return float(str(x).strip())
    except Exception:
        return None


def _read_close_map(path: str):
    """
    Supports BOTH of these CSV shapes:

    A) Historical:
       Date,Open,High,Low,Close
       1793-03-01,19.39,19.39,19.39,19.39

    B) Intraday-ish:
       Symbol,Date,Time,Open,High,Low,Close
       XAGUSD,2026-01-19,20:48:16,91.36,94.67,91.10,94.62

    Returns:
      close_by_date: { 'YYYY-MM-DD': close_float }
      stats: { rows, parsed, min_date, max_date }
    """
    close_by_date = {}
    rows = 0
    parsed = 0
    min_date = None
    max_date = None

    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        # Normalize headers once (DictReader preserves exact header names)
        # We'll look up by common variants.
        for row in reader:
            rows += 1

            d = (row.get("Date") or row.get("date") or "").strip()
            # Some files might use "Close" or "close"; rarely "Adj Close"
            c = (row.get("Close") or row.get("close") or row.get("Adj Close") or row.get("adj close") or "").strip()

            if not d or not c:
                continue

            val = _safe_float(c)
            if val is None:
                continue

            # If there are multiple rows for the same date (intraday),
            # keep the LAST one encountered. That’s fine for our backfill.
            close_by_date[d] = val
            parsed += 1

            if min_date is None or d < min_date:
                min_date = d
            if max_date is None or d > max_date:
                max_date = d

    return close_by_date, {
        "rows": rows,
        "parsed": parsed,
        "min_date": min_date,
        "max_date": max_date,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            qs = parse_qs(urlparse(self.path).query)

            # auth (same pattern as your cron endpoint)
            cron_secret = (os.getenv("CRON_SECRET", "") or "").strip()
            provided = (qs.get("secret", [""])[0] or "").strip()

            auth_header = (self.headers.get("Authorization") or "").strip()
            bearer = ""
            if auth_header.lower().startswith("bearer "):
                bearer = auth_header.split(" ", 1)[1].strip()

            ok_auth = bool(cron_secret) and (provided == cron_secret or bearer == cron_secret)
            if not ok_auth:
                return send_json(self, 401, {
                    "ok": False,
                    "error": "Unauthorized",
                    "hint": "Provide Authorization: Bearer <CRON_SECRET> or ?secret=<CRON_SECRET>"
                })

            # chunk control
            cursor = (qs.get("cursor", [""])[0] or "").strip()  # start date inclusive (YYYY-MM-DD)
            limit = int((qs.get("limit", ["500"])[0] or "500").strip())
            if limit < 50:
                limit = 50
            # You CAN raise this, but too high may time out on Vercel.
            if limit > 5000:
                limit = 5000

            # Load CSVs
            if not os.path.exists(GOLD_CSV):
                return send_json(self, 400, {"ok": False, "error": f"Missing {GOLD_CSV} in repo"})
            if not os.path.exists(SILVER_CSV):
                return send_json(self, 400, {"ok": False, "error": f"Missing {SILVER_CSV} in repo"})

            gold, gold_stats = _read_close_map(GOLD_CSV)
            silver, silver_stats = _read_close_map(SILVER_CSV)

            # intersection of dates
            common_dates = sorted(set(gold.keys()) & set(silver.keys()))
            if not common_dates:
                return send_json(self, 400, {
                    "ok": False,
                    "error": "No overlapping dates found between gold and silver CSV files.",
                    "gold_stats": gold_stats,
                    "silver_stats": silver_stats,
                    "hint": "This usually means one CSV is only 'today' data. Confirm /data/xauusd.csv and /data/xagusd.csv are BOTH the long historical files."
                })

            overlap_stats = {
                "count": len(common_dates),
                "min_date": common_dates[0],
                "max_date": common_dates[-1],
            }

            # determine start index by cursor
            start_idx = 0
            if cursor:
                # first date >= cursor
                for i, d in enumerate(common_dates):
                    if d >= cursor:
                        start_idx = i
                        break
                else:
                    return send_json(self, 200, {
                        "ok": True,
                        "processed": 0,
                        "next_cursor": None,
                        "gold_stats": gold_stats,
                        "silver_stats": silver_stats,
                        "overlap_stats": overlap_stats,
                        "message": "Cursor beyond last date; backfill already complete."
                    })

            batch = common_dates[start_idx:start_idx + limit]
            if not batch:
                return send_json(self, 200, {
                    "ok": True,
                    "processed": 0,
                    "next_cursor": None,
                    "gold_stats": gold_stats,
                    "silver_stats": silver_stats,
                    "overlap_stats": overlap_stats,
                    "message": "No rows to process."
                })

            now_utc = datetime.now(timezone.utc).isoformat()

            conn = db_connect()
            try:
                cur = conn.cursor()
                processed = 0
                skipped_zero_silver = 0

                for d in batch:
                    g = gold.get(d)
                    s = silver.get(d)
                    if g is None or s is None:
                        continue
                    if s == 0:
                        skipped_zero_silver += 1
                        continue

                    gsr = g / s

                    cur.execute(
                        """
                        insert into gsr_daily (d, gold_usd, silver_usd, gsr, fetched_at_utc, source)
                        values (%s, %s, %s, %s, %s, %s)
                        on conflict (d) do update
                          set gold_usd = excluded.gold_usd,
                              silver_usd = excluded.silver_usd,
                              gsr = excluded.gsr,
                              fetched_at_utc = excluded.fetched_at_utc,
                              source = excluded.source;
                        """,
                        (d, g, s, gsr, now_utc, "csv_backfill")
                    )
                    processed += 1

                conn.commit()

            finally:
                try:
                    conn.close()
                except Exception:
                    pass

            next_cursor = None
            if (start_idx + len(batch)) < len(common_dates):
                next_cursor = common_dates[start_idx + len(batch)]

            return send_json(self, 200, {
                "ok": True,
                "processed": processed,
                "batch_size": len(batch),
                "skipped_zero_silver": skipped_zero_silver,
                "next_cursor": next_cursor,
                "limit": limit,
                "range": {"from": batch[0], "to": batch[-1]},
                "gold_stats": gold_stats,
                "silver_stats": silver_stats,
                "overlap_stats": overlap_stats,
                "note": "Call again with ?cursor=<next_cursor> until next_cursor is null."
            })

        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": str(e)})

    def log_message(self, format, *args):
        return
