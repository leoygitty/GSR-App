from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import datetime
import json
import urllib.request
import urllib.error

# Import fallback to avoid Vercel module-path edge cases
try:
    from ._utils import db_connect, send_json
except Exception:
    from api._utils import db_connect, send_json


# Free / no-key source (GoldPrice.org JSON endpoint)
# Returns JSON with items[0].xauPrice and items[0].xagPrice in USD
GOLDPRICE_URL = "https://data-asg.goldprice.org/dbXRates/USD"

# Update policy:
# - If today's UTC row missing -> update
# - If fetched_at_utc older than STALE_MINUTES -> update
STALE_MINUTES_DEFAULT = 55

# If force=1, avoid hammering the upstream on rapid clicks
FORCE_COOLDOWN_SECONDS = 60

# Advisory lock key (any consistent 64-bit int is fine)
ADVISORY_LOCK_KEY = 731234567890  # arbitrary constant


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def _fetch_goldprice_prices():
    """
    Fetch gold (XAU) and silver (XAG) spot prices in USD from GOLDPRICE_URL.
    Expected JSON: { "items": [ { "xauPrice": <num>, "xagPrice": <num>, ... } ], ... }
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; GSR-App/1.0)",
        "Accept": "application/json",
        # These two headers help with some anti-bot/CDN configs
        "Referer": "https://goldprice.org/",
        "Origin": "https://goldprice.org",
    }

    req = urllib.request.Request(GOLDPRICE_URL, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8")

    data = json.loads(raw)
    items = data.get("items") or []
    if not items:
        raise ValueError("GoldPrice response missing items[]")

    it = items[0] or {}
    gold = it.get("xauPrice")
    silver = it.get("xagPrice")

    if gold is None or silver is None:
        raise ValueError(f"Missing xauPrice/xagPrice in response: {it}")

    gold = float(gold)
    silver = float(silver)
    if gold <= 0 or silver <= 0:
        raise ValueError(f"Non-positive prices: gold={gold}, silver={silver}")

    gsr = gold / silver
    return gold, silver, gsr


def _row_to_latest(row):
    # row: (d, gold_usd, silver_usd, gsr, fetched_at_utc, source)
    d, g, s, r, fetched_at, source = row
    return {
        "date": str(d),
        "gold_usd": str(g),
        "silver_usd": str(s),
        "gsr": str(r),
        "fetched_at_utc": str(fetched_at),
        "source": str(source),
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            qs = parse_qs(urlparse(self.path).query)

            # limit parsing
            limit_raw = (qs.get("limit", ["5000"])[0] or "5000").strip()
            try:
                limit = int(limit_raw)
            except Exception:
                limit = 5000
            if limit < 1:
                limit = 1
            if limit > 50000:
                limit = 50000

            # self-heal controls
            force = (qs.get("force", ["0"])[0] or "0").strip().lower() in ("1", "true", "yes", "on")
            stale_minutes_raw = (
                (qs.get("stale_minutes", [str(STALE_MINUTES_DEFAULT)])[0] or str(STALE_MINUTES_DEFAULT)).strip()
            )
            try:
                stale_minutes = int(stale_minutes_raw)
            except Exception:
                stale_minutes = STALE_MINUTES_DEFAULT
            stale_minutes = max(1, min(stale_minutes, 24 * 60))

            now_utc = _utc_now()
            today_utc = now_utc.date()
            stale_cutoff = now_utc - datetime.timedelta(minutes=stale_minutes)
            force_cutoff = now_utc - datetime.timedelta(seconds=FORCE_COOLDOWN_SECONDS)

            conn = db_connect()
            try:
                cur = conn.cursor()

                # Helper: read today's row
                def read_today():
                    cur.execute(
                        """
                        SELECT d, gold_usd, silver_usd, gsr, fetched_at_utc, source
                        FROM gsr_daily
                        WHERE d = %s
                        LIMIT 1;
                        """,
                        (today_utc,),
                    )
                    return cur.fetchone()

                # 1) Read today's row (UTC) if present
                today_row = read_today()

                # 2) Decide whether we should update
                should_update = False
                if not today_row:
                    should_update = True
                else:
                    fetched_at = today_row[4]
                    try:
                        if force:
                            should_update = fetched_at < force_cutoff
                        else:
                            should_update = fetched_at < stale_cutoff
                    except Exception:
                        should_update = True

                # 3) If missing/stale, try to acquire advisory lock and update
                updated = False
                update_error = None
                got_lock = False

                if should_update:
                    try:
                        cur.execute("SELECT pg_try_advisory_lock(%s);", (ADVISORY_LOCK_KEY,))
                        got_lock = bool(cur.fetchone()[0])
                    except Exception:
                        got_lock = False

                    if got_lock:
                        try:
                            gold, silver, gsr = _fetch_goldprice_prices()
                            # Use a fresh timestamp at write time
                            write_ts = _utc_now()

                            cur.execute(
                                """
                                INSERT INTO gsr_daily (d, gold_usd, silver_usd, gsr, fetched_at_utc, source)
                                VALUES (%s, %s, %s, %s, %s, %s)
                                ON CONFLICT (d) DO UPDATE SET
                                  gold_usd       = EXCLUDED.gold_usd,
                                  silver_usd     = EXCLUDED.silver_usd,
                                  gsr            = EXCLUDED.gsr,
                                  fetched_at_utc = EXCLUDED.fetched_at_utc,
                                  source         = EXCLUDED.source;
                                """,
                                (today_utc, gold, silver, gsr, write_ts, "latest_goldprice"),
                            )
                            conn.commit()
                            updated = True
                        except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as e:
                            update_error = str(e)
                            try:
                                conn.rollback()
                            except Exception:
                                pass
                        except Exception as e:
                            update_error = str(e)
                            try:
                                conn.rollback()
                            except Exception:
                                pass
                        finally:
                            try:
                                cur.execute("SELECT pg_advisory_unlock(%s);", (ADVISORY_LOCK_KEY,))
                            except Exception:
                                pass

                # 4) Determine latest to return:
                # Prefer today's row if it exists; otherwise fallback to newest date.
                today_row_after = read_today()
                if today_row_after:
                    latest_row = today_row_after
                else:
                    cur.execute(
                        """
                        SELECT d, gold_usd, silver_usd, gsr, fetched_at_utc, source
                        FROM gsr_daily
                        ORDER BY d DESC
                        LIMIT 1;
                        """
                    )
                    latest_row = cur.fetchone()

                if not latest_row:
                    return send_json(self, 404, {
                        "ok": False,
                        "error": "No data yet",
                        "hint": "Run /api/cron_gsr once, then /api/backfill_gsr until next_cursor is null."
                    })

                latest = _row_to_latest(latest_row)

                # 5) History (DESC then reverse to ASC)
                cur.execute(
                    """
                    SELECT d, gold_usd, silver_usd, gsr
                    FROM gsr_daily
                    ORDER BY d DESC
                    LIMIT %s;
                    """,
                    (limit,)
                )
                rows = list(cur.fetchall() or [])
                rows.reverse()
                history = [
                    {"date": str(d), "gold_usd": str(g), "silver_usd": str(s), "gsr": str(r)}
                    for (d, g, s, r) in rows
                ]

            finally:
                try:
                    conn.close()
                except Exception:
                    pass

            return send_json(self, 200, {
                "ok": True,
                "latest": latest,
                "history": history,
                "self_heal": {
                    "today_utc": str(today_utc),
                    "force": force,
                    "stale_minutes": stale_minutes,
                    "attempted": bool(should_update),
                    "updated": bool(updated),
                    "had_lock": bool(got_lock),
                    "error": update_error
                }
            })

        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": str(e)})

    def log_message(self, format, *args):
        return
