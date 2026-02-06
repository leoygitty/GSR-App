from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import os
import json
import time

try:
    from ._utils import db_connect, send_json
except Exception:
    from api._utils import db_connect, send_json

# ---- JWT / Clerk verification helpers ----
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
    tok = auth.split(" ", 1)[1].strip()
    return tok or None


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


def _num(v):
    try:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip().replace(",", "")
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _safe_str(v, max_len=180):
    s = ("" if v is None else str(v)).strip()
    if len(s) > max_len:
        s = s[:max_len]
    return s


def _clamp(n, a, b):
    return max(a, min(b, n))


def _is_allowed_metal(m):
    return m in ("gold", "silver", "platinum")


def ensure_table(conn):
    """
    Makes vault_items self-healing on new DBs.
    If you already have the table, this is a no-op.
    """
    cur = conn.cursor()
    cur.execute(
        """
        create table if not exists vault_items (
          id bigserial primary key,
          user_id text not null,
          label text not null,
          metal text not null check (metal in ('gold','silver','platinum')),
          item_type text not null,
          weight_value double precision not null,
          weight_unit text not null check (weight_unit in ('g','oz')),
          purity double precision not null,
          premium_pct double precision null,
          notes text null,
          source text null,
          shelf_section text null,
          shelf_slot integer null,
          accent text null,
          created_at timestamptz not null default now()
        );
        """
    )
    # Helpful index for fast per-user loads
    cur.execute("create index if not exists vault_items_user_created_idx on vault_items (user_id, created_at desc);")
    conn.commit()


def _fetch_jwks(jwks_url: str, ttl_seconds: int = 3600):
    now = int(time.time())
    if _JWKS_CACHE["keys"] and now < _JWKS_CACHE["exp"]:
        return _JWKS_CACHE["keys"]

    if not requests:
        raise RuntimeError("Missing dependency 'requests' (add requests + PyJWT to requirements.txt)")

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
    if not jwt:
        raise RuntimeError("Missing dependency 'PyJWT' (add requests + PyJWT to requirements.txt)")

    jwks_url = (os.environ.get("CLERK_JWKS_URL") or "").strip()
    if not jwks_url:
        raise RuntimeError("Missing env var CLERK_JWKS_URL")

    issuer = (os.environ.get("CLERK_ISSUER") or "").strip()  # recommended
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

    options = {"verify_aud": bool(audience), "require": ["exp", "iat", "sub"]}

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


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "authorization, content-type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    def do_GET(self):
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
                ensure_table(conn)
                cur = conn.cursor()
                cur.execute(
                    """
                    select
                      id, label, metal, item_type,
                      weight_value, weight_unit, purity,
                      premium_pct, notes, source,
                      shelf_section, shelf_slot, accent, created_at
                    from vault_items
                    where user_id = %s
                    order by
  coalesce(shelf_section, 'Main') asc,
  (case when shelf_slot is null then 999999 else shelf_slot end) asc,
  created_at desc
                    limit %s
                    """,
                    (user_id, limit),
                )
                rows = cur.fetchall() or []

                items = []
                for r in rows:
                    items.append({
                        "id": str(r[0]),
                        "label": r[1],
                        "metal": r[2],
                        "item_type": r[3],
                        "weight_value": float(r[4]) if r[4] is not None else None,
                        "weight_unit": r[5],
                        "purity": float(r[6]) if r[6] is not None else None,
                        "premium_pct": float(r[7]) if r[7] is not None else None,
                        "notes": r[8] or "",
                        "source": r[9] or "",
                        "shelf_section": r[10] or "Main",
                        "shelf_slot": int(r[11]) if r[11] is not None else None,
                        "accent": r[12] or None,
                        "created_at": r[13].isoformat() if r[13] else None,
                    })

                return send_json(self, 200, {
                    "ok": True,
                    "items": items,
                    "meta": {
                        "tier": "free",
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
                ensure_table(conn)
                cur = conn.cursor()

                if action == "create":
                    label = _safe_str(body.get("label"), 180)
                    metal = _safe_str(body.get("metal"), 32).lower()
                    item_type = _safe_str(body.get("item_type"), 32).lower() or "other"
                    weight_unit = _safe_str(body.get("weight_unit"), 8).lower()

                    weight_value = _num(body.get("weight_value"))
                    purity = _num(body.get("purity"))
                    premium_pct = _num(body.get("premium_pct"))
                    notes = _safe_str(body.get("notes"), 2000)
                    source = _safe_str(body.get("source"), 32) or "manual"

                    shelf_section = _safe_str(body.get("shelf_section"), 60) or "Main"
                    shelf_slot = body.get("shelf_slot", None)
                    accent = _safe_str(body.get("accent"), 24) or None

                    if not label:
                        return send_json(self, 400, {"ok": False, "error": "Label required"})
                    if not _is_allowed_metal(metal):
                        return send_json(self, 400, {"ok": False, "error": "Invalid metal"})
                    if weight_unit not in ("g", "oz"):
                        return send_json(self, 400, {"ok": False, "error": "Invalid weight_unit"})
                    if weight_value is None or weight_value <= 0:
                        return send_json(self, 400, {"ok": False, "error": "weight_value must be > 0"})
                    if purity is None or purity <= 0 or purity > 1:
                        return send_json(self, 400, {"ok": False, "error": "purity must be between 0 and 1"})

                    if premium_pct is not None and (premium_pct < 0 or premium_pct > 500):
                        return send_json(self, 400, {"ok": False, "error": "premium_pct out of range (0–500)"})

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
                        returning id, created_at
                        """,
                        (
                            user_id,
                            label,
                            metal,
                            item_type,
                            float(weight_value),
                            weight_unit,
                            float(purity),
                            float(premium_pct) if premium_pct is not None else None,
                            notes,
                            source,
                            shelf_section,
                            shelf_slot,
                            accent,
                        ),
                    )
                    new_id, created_at = cur.fetchone()
                    conn.commit()

                    return send_json(self, 200, {
                        "ok": True,
                        "item": {
                            "id": str(new_id),
                            "label": label,
                            "metal": metal,
                            "item_type": item_type,
                            "weight_value": float(weight_value),
                            "weight_unit": weight_unit,
                            "purity": float(purity),
                            "premium_pct": float(premium_pct) if premium_pct is not None else None,
                            "notes": notes,
                            "source": source,
                            "shelf_section": shelf_section,
                            "shelf_slot": shelf_slot,
                            "accent": accent,
                            "created_at": created_at.isoformat() if created_at else None,
                        }
                    })

                if action == "delete":
                    item_id = _safe_str(body.get("id"), 80)
                    if not item_id:
                        return send_json(self, 400, {"ok": False, "error": "Missing id"})

                    cur.execute("delete from vault_items where id = %s and user_id = %s", (item_id, user_id))
                    conn.commit()
                    return send_json(self, 200, {"ok": True})

                # update
                item_id = _safe_str(body.get("id"), 80)
                if not item_id:
                    return send_json(self, 400, {"ok": False, "error": "Missing id"})

                shelf_section = _safe_str(body.get("shelf_section"), 60) if ("shelf_section" in body) else None
                shelf_slot = body.get("shelf_slot", None) if ("shelf_slot" in body) else None
                accent = _safe_str(body.get("accent"), 24) if ("accent" in body) else None
                notes = _safe_str(body.get("notes"), 2000) if ("notes" in body) else None
                premium_pct = _num(body.get("premium_pct")) if ("premium_pct" in body) else None

                if shelf_slot is not None:
                    try:
                        shelf_slot = int(shelf_slot)
                    except Exception:
                        return send_json(self, 400, {"ok": False, "error": "Invalid shelf_slot"})
                    shelf_slot = _clamp(shelf_slot, 0, 9999)

                if premium_pct is not None and (premium_pct < 0 or premium_pct > 500):
                    return send_json(self, 400, {"ok": False, "error": "premium_pct out of range (0–500)"})

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
                if ("premium_pct" in body):
                    sets.append("premium_pct = %s")
                    vals.append(float(premium_pct) if premium_pct is not None else None)

                if not sets:
                    return send_json(self, 400, {"ok": False, "error": "Nothing to update"})

                vals.extend([item_id, user_id])
                cur.execute(f"update vault_items set {', '.join(sets)} where id = %s and user_id = %s", tuple(vals))
                conn.commit()
                return send_json(self, 200, {"ok": True})

            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": str(e)})

    def log_message(self, *_):
        return
