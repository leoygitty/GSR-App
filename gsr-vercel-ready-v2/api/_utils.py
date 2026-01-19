import json
import os
import re
import ssl
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import pg8000


def _parse_database_url(database_url: str) -> Dict[str, Any]:
    """Parse DATABASE_URL into pg8000.connect kwargs.

    Expected forms:
      - postgres://user:pass@host:5432/db?sslmode=require
      - postgresql://...
    """
    u = urlparse(database_url)
    if u.scheme not in ("postgres", "postgresql"):
        raise ValueError("DATABASE_URL must start with postgres:// or postgresql://")

    if not u.hostname or not u.path or len(u.path) < 2:
        raise ValueError("DATABASE_URL is missing host or database name")

    database = u.path.lstrip("/")
    port = u.port or 5432

    # Basic SSL handling. Neon typically uses sslmode=require.
    query = {k: v for k, v in [q.split("=", 1) if "=" in q else (q, "") for q in (u.query.split("&") if u.query else [])]}
    sslmode = query.get("sslmode", "")

    kwargs: Dict[str, Any] = {
        "user": u.username or "",
        "password": u.password or "",
        "host": u.hostname,
        "port": port,
        "database": database,
        "timeout": 10,
    }

    if sslmode in ("require", "verify-ca", "verify-full"):
        # pg8000 expects an ssl.SSLContext (or None). Use a default context.
        kwargs["ssl_context"] = ssl.create_default_context()

    return kwargs


def db_connect():
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("Missing DATABASE_URL env var")

    kwargs = _parse_database_url(database_url)
    return pg8000.connect(**kwargs)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def send_json(handler, status: int, payload: Any, extra_headers: Optional[Dict[str, str]] = None):
    body = json.dumps(payload, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    # same-origin default; add CORS if you want to call this API from elsewhere
    if extra_headers:
        for k, v in extra_headers.items():
            handler.send_header(k, v)
    handler.end_headers()
    handler.wfile.write(body)


def read_bearer_token(auth_header: str) -> str:
    m = re.match(r"^Bearer\s+(.+)$", auth_header.strip(), flags=re.IGNORECASE)
    return m.group(1).strip() if m else ""


def safe_decimal(x: Any) -> Decimal:
    # Handles numbers or numeric strings
    return Decimal(str(x))
