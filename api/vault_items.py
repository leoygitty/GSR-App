from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import os
import json
import time

# Import fallback to avoid Vercel module-path edge cases
try:
    from ._utils import db_connect, send_json
except Exception:
    from api._utils import db_connect, send_json

# ---- JWT / Clerk verification helpers ----
# Requires: PyJWT + requests (see requirements.txt below)
try:
    import jwt  # PyJWT
    import requests
except Exception:
    jwt = None
    requests = None

_JWKS_CACHE = {"keys": None, "exp": 0}


def _get_bearer_token(headers):
    auth = headers.get("Authorization") or headers.get("authorization") or ""
    if not auth.startswith("Bearer "):
        return None
    return auth.split(" ", 1)[1].strip() or None


def _fetch_jwks(jwks_url: str, ttl_seconds: int = 3600):
    now = int(time.time())
    if _JWKS_CACHE["keys"] and now < _JWKS_CACHE["exp"]:
        return _JWKS_CACHE["keys"]

    if not requests:
        raise RuntimeError("Missing dependency 'requests'")

    r = requests.get(jwks_url, timeout=8)
    r.raise_for_status()
    data = r.json()
    keys = data.get("keys") if isinstance(data, dict) else None
    if not keys:
        raise RuntimeError("JWKS response missing 'keys'")
    _JWKS_CACHE["keys"] = keys
    _JWKS_CACHE["exp"] = now + ttl_seconds
    return keys


def _verify_clerk_jwt(token: str):
    """
    Verifies the Clerk JWT using JWKS.
    Returns dict: { "sub": user_id, "claims": <full claims> }
    """
    if not jwt:
        raise RuntimeError("Missing dependency 'PyJWT'")

    jwks_url = (os.environ.get("CLERK_JWKS_URL") or "").strip()
    if not jwks_url:
        raise RuntimeError("Missing env var CLERK_JWKS_URL")

    # Optional hardening (recommended)
    issuer = (os.environ.get("CLERK_ISSUER") or "").strip()  # e.g. https://grateful-goose-55.clerk.accounts
    audience = (os.environ.get("CLERK_AUDIENCE") or "").strip()  # optional

    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get("kid")
    if not kid:
        raise RuntimeError("JWT missing 'kid' header")

    keys = _fetch_jwks(jwks_url)
    jwk = next((k for k in keys if k.get("kid") == kid), None)
    if not jwk:
        raise RuntimeError("No matching JWKS key for token kid")

    public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))

    options = {
        "verify_aud": bool(audience),
        "require": ["exp", "iat", "sub"],
    }

    decoded = jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        audience=audience if audience else None,
        issuer=issuer if issuer else None,
        options=options,
        leeway=20,
    )

    user_id = decoded.get("sub")
    if not user_id:
        raise RuntimeError("JWT missing 'sub' claim")

    return {"sub": user_id, "claims": decoded}


def _read_json_body(req: BaseHTTPRequestHandler):
    try:
        length = int(req.headers.get("Content-Length") or "0")
    except Exception:
        length = 0
    raw = req.rfile.read(length) if length > 0 else b"{}"
    try:
        return json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        return {}


def _clamp(n, a, b):
    return max(a, min(b, n))


def _is_allowed_metal(m):
    return m in ("gold", "silver", "platinum")


def _safe_str(v, max_len=180):
    s = ("" if v is None else str(v)).strip()
    if len(s) > max_len:
        s = s[:max_len]
    return s


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        # If you ever run into CORS issues. For same-origin, you usually won't.
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "authorization, content-type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    def do_GET(self):
        # Auth required
        try:
            token = _get_bearer_token(self.headers)
            if not token:
                return send_json(self, 401, {"ok": False, "error": "Missing Bearer token"})

            auth = _verify_clerk_jwt(token)
            user_id = auth["sub"]

            qs = parse_qs(urlparse(self.path).query)
            limit_raw = (qs.get("limit", ["200"])[0] or "200").strip()
            try:
                limit = int(limit_raw)
            except Exception:
                limit = 200
            limit = _clamp(limit, 1, 500)

            conn = db_connect()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    select
                      id,
                      user_id,
                      label,
                      metal,
                      item_type,
                      weight_value,
                      weight_unit,
                      purity,
                      premium_pct,
                      notes,
                      source,
                      shelf_section,
                      shelf_slot,
                      accent,
                      created_at
                    from vault_items
                    where user_id = %s
                    order by created_at desc
                    limit %s
                    """,
                    (user_id, limit),
                )
                rows = cur.fetchall()

                items = []
                for r in rows:
                    items.append({
                        "id": str(r[0]),
                        "user_id": r[1],
                        "label": r[2],
                        "metal": r[3],
                        "item_type": r[4],
                        "weight_value": float(r[5]) if r[5] is not None else None,
                        "weight_unit": r[6],
                        "purity": float(r[7]) if r[7] is not None else None,
                        "premium_pct": float(r[8]) if r[8] is not None else None,
                        "notes": r[9],
                        "source": r[10],
                        "shelf_section": r[11] or "Main",
                        "shelf_slot": int(r[12]) if r[12] is not None else None,
                        "accent": r[13] or None,
                        "created_at": r[14].isoformat() if r[14] else None,
                    })

                return send_json(self, 200, {
                    "ok": True,
                    "items": items,
                    "meta": {
                        "tier": "free",  # stub until entitlements
                        "count": len(items),
                        "limit": limit
                    }
                })
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": str(e)})

    def do_POST(self):
        # Auth required
        try:
            token = _get_bearer_token(self.headers)
            if not token:
                return send_json(self, 401, {"ok": False, "error": "Missing Bearer token"})

            auth = _verify_clerk_jwt(token)
            user_id = auth["sub"]

            body = _read_json_body(self)
            action = _safe_str(body.get("action"), 32).lower()

            if action not in ("create", "delete", "update"):
                return send_json(self, 400, {"ok": False, "error": "Invalid action"})

            conn = db_connect()
            try:
                cur = conn.cursor()

                if action == "create":
                    label = _safe_str(body.get("label"), 180)
                    metal = _safe_str(body.get("metal"), 32).lower()
                    item_type = _safe_str(body.get("item_type"), 32).lower()
                    weight_value = body.get("weight_value")
                    weight_unit = _safe_str(body.get("weight_unit"), 8).lower()
                    purity = body.get("purity")
                    premium_pct = body.get("premium_pct", None)
                    notes = _safe_str(body.get("notes"), 500)
                    source = _safe_str(body.get("source"), 32) or "manual"

                    # premium shelf fields (optional now; future “virtual shelf” layout uses this)
                    shelf_section = _safe_str(body.get("shelf_section"), 60) or "Main"
                    shelf_slot = body.get("shelf_slot", None)  # int or null
                    accent = _safe_str(body.get("accent"), 24)  # e.g. "gold", "silver", "plat", "blue"

                    if not label:
                        return send_json(self, 400, {"ok": False, "error": "Label required"})
                    if not _is_allowed_metal(metal):
                        return send_json(self, 400, {"ok": False, "error": "Invalid metal"})
                    if weight_unit not in ("g", "oz"):
                        return send_json(self, 400, {"ok": False, "error": "Invalid weight_unit"})
                    try:
                        weight_value = float(weight_value)
                    except Exception:
                        return send_json(self, 400, {"ok": False, "error": "Invalid weight_value"})
                    if weight_value <= 0:
                        return send_json(self, 400, {"ok": False, "error": "weight_value must be > 0"})

                    try:
                        purity = float(purity)
                    except Exception:
                        return send_json(self, 400, {"ok": False, "error": "Invalid purity"})
                    if purity <= 0 or purity > 1:
                        return send_json(self, 400, {"ok": False, "error": "purity must be between 0 and 1"})

                    if premium_pct is not None:
                        try:
                            premium_pct = float(premium_pct)
                        except Exception:
                            return send_json(self, 400, {"ok": False, "error": "Invalid premium_pct"})
                        if premium_pct < 0 or premium_pct > 500:
                            return send_json(self, 400, {"ok": False, "error": "premium_pct out of range"})

                    if shelf_slot is not None:
                        try:
                            shelf_slot = int(shelf_slot)
                        except Exception:
                            return send_json(self, 400, {"ok": False, "error": "Invalid shelf_slot"})
                        shelf_slot = _clamp(shelf_slot, 0, 9999)

                    cur.execute(
                        """
                        insert into vault_items
                        (user_id, label, metal, item_type, weight_value, weight_unit, purity, premium_pct, notes, source, shelf_section, shelf_slot, accent)
                        values
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        returning id
                        """,
                        (
                            user_id,
                            label,
                            metal,
                            item_type,
                            weight_value,
                            weight_unit,
                            purity,
                            premium_pct,
                            notes,
                            source,
                            shelf_section,
                            shelf_slot,
                            accent,
                        ),
                    )
                    new_id = cur.fetchone()[0]
                    conn.commit()

                    return send_json(self, 200, {"ok": True, "id": str(new_id)})

                if action == "delete":
                    item_id = _safe_str(body.get("id"), 80)
                    if not item_id:
                        return send_json(self, 400, {"ok": False, "error": "Missing id"})

                    cur.execute(
                        "delete from vault_items where id = %s and user_id = %s",
                        (item_id, user_id),
                    )
                    conn.commit()
                    return send_json(self, 200, {"ok": True})

                if action == "update":
                    item_id = _safe_str(body.get("id"), 80)
                    if not item_id:
                        return send_json(self, 400, {"ok": False, "error": "Missing id"})

                    # Minimal premium-ready update surface
                    shelf_section = _safe_str(body.get("shelf_section"), 60) or None
                    shelf_slot = body.get("shelf_slot", None)
                    accent = _safe_str(body.get("accent"), 24) or None
                    notes = _safe_str(body.get("notes"), 500) if ("notes" in body) else None
                    premium_pct = body.get("premium_pct", None) if ("premium_pct" in body) else None

                    if shelf_slot is not None:
                        try:
                            shelf_slot = int(shelf_slot)
                        except Exception:
                            return send_json(self, 400, {"ok": False, "error": "Invalid shelf_slot"})
                        shelf_slot = _clamp(shelf_slot, 0, 9999)

                    if premium_pct is not None:
                        try:
                            premium_pct = float(premium_pct)
                        except Exception:
                            return send_json(self, 400, {"ok": False, "error": "Invalid premium_pct"})
                        if premium_pct < 0 or premium_pct > 500:
                            return send_json(self, 400, {"ok": False, "error": "premium_pct out of range"})

                    # Build dynamic update
                    sets = []
                    vals = []
                    if shelf_section is not None:
                        sets.append("shelf_section = %s")
                        vals.append(shelf_section)
                    if shelf_slot is not None:
                        sets.append("shelf_slot = %s")
                        vals.append(shelf_slot)
                    if accent is not None:
                        sets.append("accent = %s")
                        vals.append(accent)
                    if notes is not None:
                        sets.append("notes = %s")
                        vals.append(notes)
                    if premium_pct is not None:
                        sets.append("premium_pct = %s")
                        vals.append(premium_pct)

                    if not sets:
                        return send_json(self, 400, {"ok": False, "error": "Nothing to update"})

                    vals.extend([item_id, user_id])

                    cur.execute(
                        f"update vault_items set {', '.join(sets)} where id = %s and user_id = %s",
                        tuple(vals),
                    )
                    conn.commit()
                    return send_json(self, 200, {"ok": True})

            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": str(e)})
