from http.server import BaseHTTPRequestHandler
from datetime import datetime, timezone

from ._utils import db_connect, send_json


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            conn = db_connect()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    select d, gold_usd, silver_usd, gsr, fetched_at_utc, source
                    from gsr_daily
                    order by d desc
                    limit 1;
                    """
                )
                row = cur.fetchone()

                cur.execute(
                    """
                    select d, gsr
                    from gsr_daily
                    order by d asc;
                    """
                )
                history = cur.fetchall() or []
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

            hist = [{"date": str(d), "gsr": str(gsr)} for (d, gsr) in history]

            return send_json(self, 200, {
                "ok": True,
                "latest": latest,
                "history": hist,
            })
        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": str(e)})

    def log_message(self, format, *args):
        return
