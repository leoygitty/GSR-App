from http.server import BaseHTTPRequestHandler
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
                    select d, gold_usd, silver_usd, gsr
                    from gsr_daily
                    order by d asc;
                    """
                )
                history_rows = cur.fetchall() or []

            finally:
                try:
                    conn.close()
                except Exception:
                    pass

            if not row:
                return send_json(self, 404, {
                    "ok": False,
                    "error": "No data yet",
                    "hint": "Run /api/cron_gsr once (with secret) or run /api/backfill_gsr to backfill history."
                })

            latest = {
                "date": str(row[0]),
                "gold_usd": str(row[1]),
                "silver_usd": str(row[2]),
                "gsr": str(row[3]),
                "fetched_at_utc": str(row[4]),
                "source": str(row[5]),
            }

            history = [{
                "date": str(r[0]),
                "gold_usd": str(r[1]),
                "silver_usd": str(r[2]),
                "gsr": str(r[3]),
            } for r in history_rows]

            return send_json(self, 200, {
                "ok": True,
                "latest": latest,
                "history": history,
            })

        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": str(e)})

    def log_message(self, format, *args):
        return
