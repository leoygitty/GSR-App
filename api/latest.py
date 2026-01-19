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
                    "hint": "Run /api/cron_gsr once (with secret) after creating the table, or run /api/backfill."
                })

            # latest
            latest = {
                "date": str(row[0]),
                "gold_usd": str(row[1]),
                "silver_usd": str(row[2]),
                "gsr": str(row[3]),
                "fetched_at_utc": str(row[4]),
                # source is jsonb; return as object when possible
                "source": row[5] if isinstance(row[5], (dict, list)) else (row[5] or {})
            }

            # history
            history = []
            for (d, g, s, gsr) in history_rows:
                history.append({
                    "date": str(d),
                    "gold_usd": str(g),
                    "silver_usd": str(s),
                    "gsr": str(gsr),
                })

            return send_json(self, 200, {
                "ok": True,
                "latest": latest,
                "history": history,
            })

        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": str(e)})

    def log_message(self, format, *args):
        return
