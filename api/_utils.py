import json
import os
import ssl
import time
import base64
import hmac
import hashlib
from urllib.parse import urlparse, parse_qsl

import pg8000.dbapi


def _pick_database_url() -> str:
    """
    Supports common env var names across Neon + Vercel.
    """
    return (
        os.getenv("DATABASE_URL")
        or os.getenv("POSTGRES_URL")
        or os.getenv("POSTGRES_URL_NON_POOLING")
        or os.getenv("NEON_DATABASE_URL")
        or os.getenv("PGURL")
        or ""
    )


def db_connect():
    """
    Connect to Postgres (Neon) using pg8000 (pure Python).
    Enforces SSL when sslmode=require or when host looks like Neon.
    """
    url = _pick_database_url()
    if not url:
        raise RuntimeError(
            "Missing database URL. Set DATABASE_URL (recommended) or POSTGRES_URL in Vercel Environment Variables."
        )

    u = urlparse(url)
    if u.scheme not in ("postgres", "postgresql"):
        raise RuntimeError(f"Unsupported DB scheme: {u.scheme}")

    query = dict(parse_qsl(u.query or ""))

    user = (u.username or "").strip()
    password = u.password or ""
    host = (u.hostname or "").strip()
    port = int(u.port or 5432)
    database = (u.path or "").lstrip("/").strip()

    if not (user and host and database):
        raise RuntimeError("Invalid DATABASE_URL/POSTGRES_URL: missing user/host/db name.")

    sslmode = (query.get("sslmode") or "").lower()

    # Neon requires TLS; many Neon URLs include sslmode=require. We enforce SSL if:
    # - sslmode=require, OR
    # - hostname looks like Neon, OR
    # - user explicitly set PGSSLMODE=require (not parsed here but common)
    force_ssl = sslmode == "require" or host.endswith(".neon.tech") or host.endswith(".neon.tech.")

    ssl_ctx = ssl.create_default_context() if force_ssl else None

    return pg8000.dbapi.connect(
        user=user,
        password=password,
        host=host,
        port=port,
        database=database,
        ssl_context=ssl_ctx,
        timeout=10,
    )


def send_json(handler, status: int, payload: dict):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


# =============================================================================
# Step 1 (Stripe tier gating) helpers
# =============================================================================

# Required env var for signing login tokens (set in Vercel):
# AUTH_SECRET = long random string
_AUTH_SECRET = os.getenv("AUTH_SECRET", "").encode("utf-8")


def ensure_users_table(conn):
    """
    Stores subscription tier entitlements.
    """
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
          email TEXT PRIMARY KEY,
          stripe_customer_id TEXT,
          tier TEXT NOT NULL DEFAULT 'free',
          status TEXT NOT NULL DEFAULT 'inactive',
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    conn.commit()


def upsert_user(conn, email: str, stripe_customer_id: str, tier: str, status: str):
    tier = (tier or "free").lower()
    if tier not in ("free", "pro", "elite"):
        tier = "free"

    status = (status or "inactive").lower()

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO users (email, stripe_customer_id, tier, status, updated_at)
        VALUES (%s, %s, %s, %s, now())
        ON CONFLICT (email) DO UPDATE SET
          stripe_customer_id = EXCLUDED.stripe_customer_id,
          tier = EXCLUDED.tier,
          status = EXCLUDED.status,
          updated_at = now()
        """,
        (email, stripe_customer_id, tier, status),
    )
    conn.commit()


def get_user_tier(conn, email: str) -> str:
    cur = conn.cursor()
    cur.execute("SELECT tier FROM users WHERE email = %s", (email,))
    row = cur.fetchone()
    if not row or not row[0]:
        return "free"
    t = (row[0] or "free").lower()
    return t if t in ("free", "pro", "elite") else "free"


# ---- Token signing (stdlib only; no extra deps)

def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("utf-8").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("utf-8"))


def sign_token(payload: dict, days: int = 30) -> str:
    """
    Creates a compact signed token: base64url(json).base64url(hmac)
    """
    if not _AUTH_SECRET:
        raise RuntimeError("AUTH_SECRET env var is missing")

    p = dict(payload or {})
    p["exp"] = int(time.time()) + int(days) * 24 * 3600

    body = _b64url(json.dumps(p, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(_AUTH_SECRET, body.encode("utf-8"), hashlib.sha256).digest()
    return body + "." + _b64url(sig)


def verify_token(token: str) -> dict:
    """
    Returns decoded payload dict if valid; otherwise returns None.
    """
    try:
        if not token or "." not in token or not _AUTH_SECRET:
            return None

        body, sig = token.split(".", 1)
        expected = hmac.new(_AUTH_SECRET, body.encode("utf-8"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url(expected), sig):
            return None

        payload = json.loads(_b64url_decode(body).decode("utf-8"))
        exp = int(payload.get("exp", 0) or 0)
        if exp and exp < int(time.time()):
            return None

        return payload
    except Exception:
        return None


# ---- Stripe price → tier mapping (set these env vars in Vercel)
# STRIPE_PRICE_PRO, STRIPE_PRICE_ELITE

def tier_from_price_id(price_id: str) -> str:
    pro = os.getenv("STRIPE_PRICE_PRO", "").strip()
    elite = os.getenv("STRIPE_PRICE_ELITE", "").strip()

    if price_id and elite and price_id == elite:
        return "elite"
    if price_id and pro and price_id == pro:
        return "pro"
    return "free"
