from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone
import csv
import os

from api._utils import db_connect, send_json


DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
GOLD_CSV = os.path.join(DATA_DIR, "xauusd.csv")
SILVER_CSV = os.path.join(DATA_DIR, "xagusd.csv")


def _read_close_map(path: str):
    """
    Reads a CSV with header: Date,Open,High,Low,Close
    Returns dict: { 'YYYY-MM-DD': close_float }
    """
    out = {}
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = (row.get("Date") or row.get("date") or "").strip()
            c = (row.get("Close") or row.get("close") or "").strip()
            if not d or not c:
                continue
            try:
                out[d] = float(c)
            except Exception:
                continue
    return out


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            qs = parse_qs(urlparse(self.path).query)

            # auth
            cron_secret = os.getenv("CRON_SECRET", "")
            provided = (qs.get("secret", [""])[0] or "").strip()

            auth_header = (self.headers.get("Authorization") or "").strip()
            bearer = ""
            if auth_header.lower().startswith("bearer "):
                bearer = auth_header.split(" ", 1)[1].strip()

            ok_auth = False
            if cron_secret and (provided == cron_secret or bearer == cron_secret):
                ok_auth = True

            if not ok_auth:
                return send_json(self, 401, {
                    "ok": False,
                    "error": "Unauthorized",
                    "hint": "Provide Authorization: Bearer <CRON_SECRET> or ?secret=<CRON_SECRET>"
                })

            cursor = (qs.get("cursor", [""])[0] or "").strip()
            limit = int((qs.get("limit", ["500"])[0] or "500").strip())
            if limit < 50:
                limit = 50
            if limit > 5000:
                limit = 5000

            if not os.path.exists(GOLD_CSV):
                return send_json(self, 400, {"ok": False, "error": f"Missing {GOLD_CSV} in repo"})
            if not os.path.exists(SILVER_CSV):
                return send_json(self, 400, {"ok": False, "error": f"Missing {SILVER_CSV} in repo"})

            gold = _read_close_map(GOLD_CSV)
            silver = _read_close_map(SILVER_CSV)

            common_dates = sorted(set(gold.keys()) & set(silver.keys()))
            if not common_dates:
                return send_json(self, 400, {
                    "ok": False,
                    "error": "No overlapping dates found between gold and silver CSV files.",
                    "hint": "Verify both CSVs have matching Date values and similar date ranges."
                })

            start_idx = 0
            if cursor:
                for i, d in enumerate(common_dates):
                    if d >= cursor:
                        start_idx = i
                        break
                else:
                    return send_json(self, 200, {
                        "ok": True,
                        "processed": 0,
                        "next_cursor": None,
                        "message": "Cursor beyond last date; backfill already complete."
                    })

            batch = common_dates[start_idx:start_idx + limit]
            if not batch:
                return send_json(self, 200, {
                    "ok": True,
                    "processed": 0,
                    "next_cursor": None,
                    "message": "No rows to process."
                })

            now_utc = datetime.now(timezone.utc).isoformat()

            conn = db_connect()
            try:
                cur = conn.cursor()
                for d in batch:
                    g = gold[d]
                    s = silver[d]
                    if s == 0:
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
                              source = excluded.source
                        """,
                        (d, g, s, gsr, now_utc, "csv_backfill")
                    )

                conn.commit()
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

            next_cursor = None
            if (start_idx + limit) < len(common_dates):
                next_cursor = common_dates[start_idx + limit]

            return send_json(self, 200, {
                "ok": True,
                "processed": len(batch),
                "next_cursor": next_cursor,
                "limit": limit,
                "range": {"from": batch[0], "to": batch[-1]},
                "note": "Call again with ?cursor=<next_cursor> until next_cursor is null."
            })

        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": str(e)})

    def log_message(self, format, *args):
        return
