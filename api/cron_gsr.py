from http.server import BaseHTTPRequestHandler
import os
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

from ._utils import db_connect, send_json, read_bearer_token, utc_now_iso, safe_decimal
from ._pricing import fetch_spot_prices_usd


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            # Auth: Authorization: Bearer <CRON_SECRET>
            cron_secret = os.environ.get("CRON_SECRET", "").strip()
            auth = self.headers.get("Authorization", "")
            token = read_bearer_token(auth)

            # Also allow manual testing with ?secret=...
            qs = parse_qs(urlparse(self.path).query)
            token_qs = (qs.get("secret", [""])[0] or "").strip()

            if cron_secret:
                if token != cron_secret and token_qs != cron_secret:
                    return send_json(self, 401, {
                        "ok": False,
                        "error": "Unauthorized",
                        "hint": "Provide Authorization: Bearer <CRON_SECRET> or ?secret=<CRON_SECRET>"
                    })

            gold_usd, silver_usd, gold_raw, silver_raw = fetch_spot_prices_usd()
            if silver_usd == 0:
                return send_json(self, 500, {"ok": False, "error": "Silver price returned 0"})

            gsr = (gold_usd / silver_usd)

            d = datetime.now(timezone.utc).date()

            conn = db_connect()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    insert into gsr_daily (d, gold_usd, silver_usd, gsr, fetched_at_utc)
                    values (%s, %s, %s, %s, now())
                    on conflict (d) do update set
                      gold_usd = excluded.gold_usd,
                      silver_usd = excluded.silver_usd,
                      gsr = excluded.gsr,
                      fetched_at_utc = now();
                    """,
                    (d, str(gold_usd), str(silver_usd), str(gsr)),
                )
                conn.commit()
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

            return send_json(self, 200, {
                "ok": True,
                "date_utc": str(d),
                "gold_usd": str(gold_usd),
                "silver_usd": str(silver_usd),
                "gsr": str(gsr),
                "fetched_at_utc": utc_now_iso(),
                "source": {
                    "gold": gold_raw,
                    "silver": silver_raw
                }
            })
        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": str(e)})

    # Quiet default logging noise (optional)
    def log_message(self, format, *args):
        return
