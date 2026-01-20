from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from ._utils import db_connect, send_json


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            qs = parse_qs(urlparse(self.path).query)
            # Optional limit for history points (ordered ASC)
            # Default returns all rows (ok for ~15k).
            limit_str = (qs.get("limit", [""])[0] or "").strip()
            limit = None
            if limit_str:
                try:
                    limit = int(limit_str)
                except Exception:
                    limit = None

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

                if limit and limit > 0:
                    cur.execute(
                        """
                        select d, gold_usd, silver_usd, gsr
                        from gsr_daily
                        order by d desc
                        limit %s;
                        """,
                        (limit,)
                    )
                    history_rows = cur.fetchall() or []
                    # reverse to ASC for charting
                    history_rows = list(reversed(history_rows))
                else:
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
                    "hint": "Run /api/cron_gsr once (with secret) after creating the table, then run /api/backfill_gsr (with secret) to load history."
                })

            latest = {
                "date": str(row[0]),
                "gold_usd": str(row[1]),
                "silver_usd": str(row[2]),
                "gsr": str(row[3]),
                "fetched_at_utc": str(row[4]),
                "source": str(row[5]),
            }

            hist = [
                {
                    "date": str(d),
                    "gold_usd": str(gold),
                    "silver_usd": str(silver),
                    "gsr": str(gsr),
                }
                for (d, gold, silver, gsr) in history_rows
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
