from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from api._utils import db_connect, send_json


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            qs = parse_qs(urlparse(self.path).query)
            limit_str = (qs.get("limit", ["5000"])[0] or "5000").strip()

            try:
                limit = int(limit_str)
            except Exception:
                limit = 5000

            # Reasonable caps so you don't blow up payload size
            if limit < 1:
                limit = 1
            if limit > 50000:
                limit = 50000

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

                if not row:
                    return send_json(self, 404, {
                        "ok": False,
                        "error": "No data yet",
                        "hint": "Run /api/cron_gsr once (with secret) and/or run /api/backfill_gsr (with secret)."
                    })

                latest = {
                    "date": str(row[0]),
                    "gold_usd": str(row[1]),
                    "silver_usd": str(row[2]),
                    "gsr": str(row[3]),
                    "fetched_at_utc": str(row[4]),
                    "source": str(row[5]),
                }

                # Most recent N history points, returned ASC for charting
                cur.execute(
                    """
                    select d, gold_usd, silver_usd, gsr
                    from gsr_daily
                    order by d desc
                    limit %s;
                    """,
                    (limit,)
                )
                rows = cur.fetchall() or []
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

            # Reverse to ASC
            rows.reverse()

            history = [
                {
                    "date": str(d),
                    "gold_usd": str(g),
                    "silver_usd": str(s),
                    "gsr": str(r),
                }
                for (d, g, s, r) in rows
            ]

            return send_json(self, 200, {
                "ok": True,
                "latest": latest,
                "history": history,
            })

        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": str(e)})

    def log_message(self, format, *args):
        return
