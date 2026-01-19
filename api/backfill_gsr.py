from http.server import BaseHTTPRequestHandler
from datetime import datetime, timezone
import csv
import io
import json
import os
import urllib.request
import http.cookiejar
from urllib.parse import urlparse, parse_qs

from ._utils import db_connect, send_json


def _fetch_stooq_daily_csv(symbol: str) -> list[dict]:
    """
    Fetch Stooq daily historical CSV:
    https://stooq.com/q/d/l/?s=<symbol>&i=d

    Returns list of dict rows with keys like:
      Date, Open, High, Low, Close, Volume
    """
    # Some hosts behave better with a cookie jar + user-agent
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = [
        ("User-Agent", "Mozilla/5.0 (compatible; gsr-app/1.0)"),
        ("Accept", "text/csv,*/*"),
    ]

    # Warm-up (harmless)
    try:
        opener.open("https://stooq.com/", timeout=20)
    except Exception:
        pass

    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    with opener.open(url, timeout=30) as resp:
        raw = resp.read().decode("utf-8", errors="replace")

    buf = io.StringIO(raw)
    reader = csv.DictReader(buf)

    rows = []
    for r in reader:
        # Stooq uses "Date" + "Close"
        if r.get("Date") and r.get("Close"):
            rows.append(r)
    return rows


def _rows_to_close_map(rows: list[dict]) -> dict:
    """
    Convert Stooq rows into { "YYYY-MM-DD": float(close) }
    """
    out = {}
    for r in rows:
        d = (r.get("Date") or "").strip()
        c = (r.get("Close") or "").strip()
        if not d or not c:
            continue
        try:
            out[d] = float(c)
        except Exception:
            continue
    return out


def _auth_ok(handler) -> bool:
    """
    Auth rule:
    - If CRON_SECRET is set in env, require either:
        Authorization: Bearer <CRON_SECRET>
      OR
        ?secret=<CRON_SECRET>
    - If CRON_SECRET is NOT set, allow (not recommended).
    """
    secret = os.environ.get("CRON_SECRET", "").strip()
    if not secret:
        return True

    auth = (handler.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token == secret:
            return True

    try:
        q = parse_qs(urlparse(handler.path).query)
        qs = (q.get("secret", [""])[0] or "").strip()
        if qs == secret:
            return True
    except Exception:
        pass

    return False


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            if not _auth_ok(self):
                return send_json(self, 401, {
                    "ok": False,
                    "error": "Unauthorized",
                    "hint": "Set CRON_SECRET in Vercel env vars, then call /api/backfill_gsr?secret=... or use Authorization: Bearer ..."
                })

            # Fetch long history (daily EOD)
            gold_rows = _fetch_stooq_daily_csv("xauusd")
            silver_rows = _fetch_stooq_daily_csv("xagusd")

            gold_map = _rows_to_close_map(gold_rows)
            silver_map = _rows_to_close_map(silver_rows)

            common_dates = sorted(set(gold_map.keys()) & set(silver_map.keys()))
            if not common_dates:
                return send_json(self, 500, {
                    "ok": False,
                    "error": "No overlapping dates between XAUUSD and XAGUSD series.",
                })

            now_utc = datetime.now(timezone.utc).isoformat()

            # Insert/Upsert into Neon
            conn = db_connect()
            upserted = 0
            try:
                cur = conn.cursor()

                # Ensure table exists with the columns you use
                cur.execute(
                    """
                    create table if not exists gsr_daily (
                      d date primary key,
                      gold_usd numeric not null,
                      silver_usd numeric not null,
                      gsr numeric not null,
                      fetched_at_utc timestamptz not null default now(),
                      source jsonb not null default '{}'::jsonb
                    );
                    """
                )

                source_obj = {
                    "provider": "stooq",
                    "symbols": {"gold": "xauusd", "silver": "xagusd"},
                    "kind": "daily_eod_close",
                    "note": "Backfilled from public daily CSV series; not intraday spot."
                }
                source_json = json.dumps(source_obj)

                for d in common_dates:
                    g = gold_map.get(d)
                    s = silver_map.get(d)
                    if g is None or s is None:
                        continue
                    if s == 0:
                        continue

                    gsr = g / s

                    cur.execute(
                        """
                        insert into gsr_daily (d, gold_usd, silver_usd, gsr, fetched_at_utc, source)
                        values (%s, %s, %s, %s, %s, %s::jsonb)
                        on conflict (d) do update set
                          gold_usd = excluded.gold_usd,
                          silver_usd = excluded.silver_usd,
                          gsr = excluded.gsr,
                          fetched_at_utc = excluded.fetched_at_utc,
                          source = excluded.source;
                        """,
                        (d, g, s, gsr, now_utc, source_json)
                    )
                    upserted += 1

                conn.commit()
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

            return send_json(self, 200, {
                "ok": True,
                "rows_upserted": upserted,
                "date_range": {"start": common_dates[0], "end": common_dates[-1]},
                "series": {"gold": "xauusd", "silver": "xagusd"},
                "note": "This backfill uses daily EOD close values. Your cron can continue storing the latest spot snapshot separately."
            })

        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": str(e)})

    def log_message(self, format, *args):
        return
