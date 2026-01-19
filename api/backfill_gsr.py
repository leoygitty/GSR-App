from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone
import os
import csv
import json

from ._utils import db_connect, send_json


def _read_prices_by_date(csv_path: str) -> dict:
    """
    Expects CSV columns like:
    Symbol,Date,Time,Open,High,Low,Close
    Returns { 'YYYY-MM-DD': close_float }
    If multiple rows per day exist, last one wins.
    """
    prices = {}
    if not os.path.exists(csv_path):
        return prices

    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = (row.get("Date") or "").strip()
            close = row.get("Close")
            if not d or close is None:
                continue
            try:
                prices[d] = float(str(close).strip())
            except Exception:
                continue
    return prices


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            # --- Auth (reuse CRON_SECRET so random people can't spam inserts) ---
            qs = parse_qs(urlparse(self.path).query)
            secret = (qs.get("secret", [""])[0] or "").strip()
            expected = (os.environ.get("CRON_SECRET") or "").strip()

            if expected:
                auth = (self.headers.get("Authorization") or "").strip()
                bearer_ok = auth == f"Bearer {expected}"
                query_ok = secret == expected
                if not (bearer_ok or query_ok):
                    return send_json(self, 401, {
                        "ok": False,
                        "error": "Unauthorized",
                        "hint": "Provide Authorization: Bearer <CRON_SECRET> or ?secret=<CRON_SECRET>"
                    })

            # --- Locate CSVs in repo ---
            root = os.path.dirname(os.path.dirname(__file__))  # repo root (api/ is one level down)
            gold_csv = os.path.join(root, "data", "xauusd.csv")
            silver_csv = os.path.join(root, "data", "xagusd.csv")

            gold = _read_prices_by_date(gold_csv)
            silver = _read_prices_by_date(silver_csv)

            if not gold or not silver:
                return send_json(self, 400, {
                    "ok": False,
                    "error": "Missing or empty CSVs",
                    "details": {
                        "gold_csv_exists": os.path.exists(gold_csv),
                        "silver_csv_exists": os.path.exists(silver_csv),
                        "gold_rows": len(gold),
                        "silver_rows": len(silver),
                        "expected_paths": {
                            "gold": "data/xauusd.csv",
                            "silver": "data/xagusd.csv"
                        }
                    }
                })

            # Intersection of dates
            dates = sorted(set(gold.keys()) & set(silver.keys()))
            if not dates:
                return send_json(self, 400, {
                    "ok": False,
                    "error": "No overlapping dates between gold and silver CSVs",
                    "gold_dates": len(gold),
                    "silver_dates": len(silver)
                })

            now_utc = datetime.now(timezone.utc)

            # --- Insert / upsert into Neon ---
            conn = db_connect()
            inserted = 0
            updated = 0
            skipped = 0

            try:
                cur = conn.cursor()
                for d in dates:
                    g = gold.get(d)
                    s = silver.get(d)
                    if g is None or s is None or s == 0:
                        skipped += 1
                        continue

                    gsr = g / s

                    src = {
                        "type": "csv_backfill",
                        "gold_file": "data/xauusd.csv",
                        "silver_file": "data/xagusd.csv",
                        "as_of": d
                    }

                    # Upsert by primary key (d)
                    cur.execute(
                        """
                        insert into gsr_daily (d, gold_usd, silver_usd, gsr, fetched_at_utc, source)
                        values (%s, %s, %s, %s, %s, %s::jsonb)
                        on conflict (d) do update
                        set gold_usd = excluded.gold_usd,
                            silver_usd = excluded.silver_usd,
                            gsr = excluded.gsr,
                            fetched_at_utc = excluded.fetched_at_utc,
                            source = excluded.source
                        """,
                        (d, g, s, gsr, now_utc, json.dumps(src))
                    )
                conn.commit()

                # Count rows after backfill
                cur.execute("select count(*) from gsr_daily;")
                total = cur.fetchone()[0]

                # Compute how many rows were upserted isn’t directly returned by psycopg cursor reliably here,
                # so we return the date range + total count as proof.
                return send_json(self, 200, {
                    "ok": True,
                    "message": "Backfill complete (upserted by date).",
                    "dates": {
                        "first": dates[0],
                        "last": dates[-1],
                        "count": len(dates)
                    },
                    "table_rows_now": total
                })

            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": str(e)})

    def log_message(self, format, *args):
        return
