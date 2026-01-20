from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from ._utils import db_connect, send_json


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            qs = parse_qs(urlparse(self.path).query)

            # Default: last 2000 points (keeps UI fast + avoids huge JSON)
            limit_raw = (qs.get("limit", ["2000"])[0] or "2000").strip()
            try:
                limit = int(limit_raw)
            except Exception:
                limit = 2000

            if limit < 50:
                limit = 50
            if limit > 10000:
                limit = 10000

            conn = db_connect()
            try:
                cur = conn.cursor()

                # Latest row
                cur.execute(
                    """
                    select d, gold_usd, silver_usd, gsr, fetched_at_utc, source
                    from gsr_daily
                    order by d desc
                    limit 1;
                    """
                )
                row = cur.fetchone()

                # History window (last N rows), then sort ascending for charting
                cur.execute(
                    """
                    select d, gold_usd, silver_usd, gsr
                    from gsr_daily
                    order by d desc
                    limit %s;
                    """,
                    (limit,)
                )
                hist_rows = cur.fetchall() or []

            finally:
                try:
                    conn.close()
                except Exception:
                    pass

            if not row:
                return send_json(self, 404, {
                    "ok": False,
                    "error": "No data yet",
                    "hint": "Run /api/cron_gsr once (with secret) after creating the table."
                })

            latest = {
                "date": str(row[0]),
                "gold_usd": str(row[1]),
                "silver_usd": str(row[2]),
                "gsr": str(row[3]),
                "fetched_at_utc": str(row[4]),
                "source": str(row[5]),
            }

            # convert to ascending by date
            hist_rows.reverse()

            history = []
            for (d, gold_usd, silver_usd, gsr) in hist_rows:
                history.append({
                    "date": str(d),
                    "gold_usd": str(gold_usd),
                    "silver_usd": str(silver_usd),
                    "gsr": str(gsr),
                })

            return send_json(self, 200, {
                "ok": True,
                "latest": latest,
                "history": history,
                "limit": limit,
            })

        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": str(e)})

    def log_message(self, format, *args):
        return
