import json
import os
import ssl
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
