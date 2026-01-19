from http.server import BaseHTTPRequestHandler
from ._utils import db_connect, send_json


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
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

                # Full history for charts (ASC by date)
                cur.execute(
                    """
                    select d, gold_usd, silver_usd, gsr
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
                    "hint": "Run /api/backfill_gsr once (with secret) to backfill history, then refresh."
                })

            latest = {
                "date": str(row[0]),
                "gold_usd": str(row[1]),
                "silver_usd": str(row[2]),
                "gsr": str(row[3]),
                "fetched_at_utc": str(row[4]),
                "source": row[5],  # jsonb is fine to return directly
            }

            hist = [
                {
                    "date": str(d),
                    "gold_usd": str(g),
                    "silver_usd": str(s),
                    "gsr": str(gsr),
                }
                for (d, g, s, gsr) in history
            ]

            return send_json(self, 200, {
                "ok": True,
                "latest": latest,
                "history": hist,
            })
        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": str(e)})

    def log_message(self, format, *args):
        return
