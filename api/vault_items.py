# api/vault_items.py
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


# ----------------------------
# Small utilities
# ----------------------------
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


def _is_allowed_item_type(t):
    return t in ("bullion", "coin", "bar", "jewelry", "other")


def _default_accent_for_metal(metal: str):
    if metal == "gold":
        return "gold"
    if metal == "silver":
        return "silver"
    if metal == "platinum":
        return "plat"
    return None


def _default_section_for_item_type(item_type: str):
    t = (item_type or "").lower()
    if t == "coin":
        return "Coins"
    if t in ("bullion", "bar"):
        return "Bullion"
    if t == "jewelry":
        return "Jewelry"
    return "Main"


# ----------------------------
# DB bootstrap / migrations
# ----------------------------
def _try_exec(cur, sql: str):
    try:
        cur.execute(sql)
        return True
    except Exception:
        return False


def ensure_table(conn):
    """
    Creates the table if missing. If it already exists, runs small additive migrations
    (ALTER TABLE ADD COLUMN) so you don't get stuck on an old schema.
    """
    cur = conn.cursor()

    # Create base table (safe on new DBs)
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
          qty integer not null default 1,
          created_at timestamptz not null default now()
        );
        """
    )

    # Additive migrations for older DBs (ignore failures)
    _try_exec(cur, "alter table vault_items add column if not exists shelf_section text null;")
    _try_exec(cur, "alter table vault_items add column if not exists shelf_slot integer null;")
    _try_exec(cur, "alter table vault_items add column if not exists accent text null;")
    _try_exec(cur, "alter table vault_items add column if not exists qty integer not null default 1;")
    _try_exec(cur, "alter table vault_items add column if not exists created_at timestamptz not null default now();")

    # Helpful indexes
    _try_exec(cur, "create index if not exists vault_items_user_created_idx on vault_items (user_id, created_at desc);")
    _try_exec(cur, "create index if not exists vault_items_user_shelf_idx on vault_items (user_id, shelf_section, shelf_slot);")
    _try_exec(cur, "create index if not exists vault_items_user_type_idx on vault_items (user_id, item_type);")

    conn.commit()


def _next_shelf_slot(cur, user_id: str, shelf_section: str):
    cur.execute(
        """
        select coalesce(max(shelf_slot), -1) + 1
        from vault_items
        where user_id = %s
          and coalesce(shelf_section, 'Main') = %s
          and shelf_slot is not null
        """,
        (user_id, shelf_section),
    )
    row = cur.fetchone()
    try:
        return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0


# ----------------------------
# Clerk JWT verification
# ----------------------------
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
    if not jwt:
        raise RuntimeError("Missing dependency 'PyJWT'")

    jwks_url = (os.environ.get("CLERK_JWKS_URL") or "").strip()
    if not jwks_url:
        raise RuntimeError("Missing env var CLERK_JWKS_URL")

    issuer = (os.environ.get("CLERK_ISSUER") or "").strip()
    audience = (os.environ.get("CLERK_AUDIENCE") or "").strip()

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


# ----------------------------
# Handler
# ----------------------------
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

            try:
                auth = _verify_clerk_jwt(token)
            except Exception as e:
                # IMPORTANT: invalid/misconfigured auth should be 401, not 500
                return send_json(self, 401, {"ok": False, "error": f"Unauthorized: {str(e)}"})

            user_id = auth["sub"]


            qs = parse_qs(urlparse(self.path).query)
            limit_raw = (qs.get("limit", ["200"])[0] or "200").strip()
            section_filter = _safe_str((qs.get("section", [""])[0] or ""), 60)
            type_filter = _safe_str((qs.get("type", [""])[0] or ""), 32).lower()

            try:
                limit = int(limit_raw)
            except Exception:
                limit = 200
            limit = _clamp(limit, 1, 500)

            if type_filter and not _is_allowed_item_type(type_filter):
                return send_json(self, 400, {"ok": False, "error": "Invalid type filter"})

            conn = db_connect()
            try:
                ensure_table(conn)
                cur = conn.cursor()

                where = ["user_id = %s"]
                vals = [user_id]

                if section_filter:
                    where.append("coalesce(shelf_section, 'Main') = %s")
                    vals.append(section_filter)

                if type_filter:
                    where.append("item_type = %s")
                    vals.append(type_filter)

                vals.append(limit)

                cur.execute(
                    f"""
                    select
                      id, label, metal, item_type,
                      weight_value, weight_unit, purity,
                      premium_pct, notes, source,
                      shelf_section, shelf_slot, accent, qty, created_at
                    from vault_items
                    where {' and '.join(where)}
                    order by
                      coalesce(shelf_section, 'Main') asc,
                      (case when shelf_slot is null then 999999 else shelf_slot end) asc,
                      created_at desc
                    limit %s
                    """,
                    tuple(vals),
                )
                rows = cur.fetchall() or []

                items = []
                for r in rows:
                    items.append(
                        {
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
                            "qty": int(r[13]) if r[13] is not None else 1,
                            "created_at": r[14].isoformat() if r[14] else None,
                        }
                    )

                # Section breakdown for UI shelves
                cur.execute(
                    """
                    select coalesce(shelf_section,'Main') as section, count(*)::int
                    from vault_items
                    where user_id = %s
                    group by 1
                    order by 1 asc
                    """,
                    (user_id,),
                )
                sec_rows = cur.fetchall() or []
                sections = [{"section": s, "count": int(c)} for (s, c) in sec_rows]

                return send_json(
                    self,
                    200,
                    {
                        "ok": True,
                        "items": items,
                        "meta": {
                            "tier": "free",
                            "count": len(items),
                            "limit": limit,
                            "sections": sections,
                        },
                    },
                )
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

            try:
                auth = _verify_clerk_jwt(token)
            except Exception as e:
                return send_json(self, 401, {"ok": False, "error": f"Unauthorized: {str(e)}"})

            user_id = auth["sub"]


            body = _read_json_body(self)
            action = _safe_str(body.get("action"), 32).lower()
            if action not in ("create", "delete", "update", "reorder"):
                return send_json(self, 400, {"ok": False, "error": "Invalid action"})

            conn = db_connect()
            try:
                ensure_table(conn)
                cur = conn.cursor()

                # ----------------------------
                # CREATE
                # ----------------------------
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

                    qty = body.get("qty", None)
                    try:
                        qty = int(qty) if qty is not None else 1
                    except Exception:
                        qty = 1
                    qty = _clamp(qty, 1, 100000)

                    shelf_section = _safe_str(body.get("shelf_section"), 60) or ""
                    shelf_slot = body.get("shelf_slot", None)
                    accent = _safe_str(body.get("accent"), 24) or None

                    # Validate
                    if not label:
                        return send_json(self, 400, {"ok": False, "error": "Label required"})
                    if not _is_allowed_metal(metal):
                        return send_json(self, 400, {"ok": False, "error": "Invalid metal"})
                    if not _is_allowed_item_type(item_type):
                        item_type = "other"
                    if weight_unit not in ("g", "oz"):
                        return send_json(self, 400, {"ok": False, "error": "Invalid weight_unit"})
                    if weight_value is None or weight_value <= 0:
                        return send_json(self, 400, {"ok": False, "error": "weight_value must be > 0"})
                    if purity is None or purity <= 0 or purity > 1:
                        return send_json(self, 400, {"ok": False, "error": "purity must be between 0 and 1"})
                    if premium_pct is not None and (premium_pct < 0 or premium_pct > 500):
                        return send_json(self, 400, {"ok": False, "error": "premium_pct out of range (0–500)"})

                    # Default shelf section by item_type if not provided
                    if not shelf_section:
                        shelf_section = _default_section_for_item_type(item_type)

                    # Shelf slot: clamp or auto-assign next slot
                    if shelf_slot is not None:
                        try:
                            shelf_slot = int(shelf_slot)
                        except Exception:
                            return send_json(self, 400, {"ok": False, "error": "Invalid shelf_slot"})
                        shelf_slot = _clamp(shelf_slot, 0, 999999)
                    else:
                        shelf_slot = _next_shelf_slot(cur, user_id, shelf_section)

                    # Accent: default to metal accent if not provided
                    if not accent:
                        accent = _default_accent_for_metal(metal)

                    cur.execute(
                        """
                        insert into vault_items
                        (user_id, label, metal, item_type, weight_value, weight_unit, purity, premium_pct, notes, source, shelf_section, shelf_slot, accent, qty)
                        values
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                            qty,
                        ),
                    )
                    new_id, created_at = cur.fetchone()
                    conn.commit()

                    return send_json(
                        self,
                        200,
                        {
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
                                "qty": qty,
                                "created_at": created_at.isoformat() if created_at else None,
                            },
                        },
                    )

                # ----------------------------
                # DELETE
                # ----------------------------
                if action == "delete":
                    item_id = _safe_str(body.get("id"), 80)
                    if not item_id:
                        return send_json(self, 400, {"ok": False, "error": "Missing id"})

                    cur.execute("delete from vault_items where id = %s and user_id = %s", (item_id, user_id))
                    conn.commit()
                    return send_json(self, 200, {"ok": True})

                # ----------------------------
                # REORDER (batch move / slot updates)
                # body: { action:"reorder", moves:[{id, shelf_section, shelf_slot}, ...] }
                # ----------------------------
                if action == "reorder":
                    moves = body.get("moves")
                    if not isinstance(moves, list) or not moves:
                        return send_json(self, 400, {"ok": False, "error": "moves[] required"})

                    # Update each item (small batch). Keep it simple + safe.
                    updated = 0
                    for m in moves[:500]:
                        iid = _safe_str((m or {}).get("id"), 80)
                        if not iid:
                            continue
                        sec = _safe_str((m or {}).get("shelf_section"), 60) or None
                        slot = (m or {}).get("shelf_slot", None)

                        if sec is not None and sec.strip() == "":
                            sec = "Main"

                        if slot is not None:
                            try:
                                slot = int(slot)
                            except Exception:
                                continue
                            slot = _clamp(slot, 0, 999999)

                        sets = []
                        vals = []

                        if sec is not None:
                            sets.append("shelf_section = %s")
                            vals.append(sec)

                        if ("shelf_slot" in (m or {})):
                            sets.append("shelf_slot = %s")
                            vals.append(slot if slot is not None else None)

                        if not sets:
                            continue

                        vals.extend([iid, user_id])
                        cur.execute(
                            f"update vault_items set {', '.join(sets)} where id = %s and user_id = %s",
                            tuple(vals),
                        )
                        updated += 1

                    conn.commit()
                    return send_json(self, 200, {"ok": True, "updated": updated})

                # ----------------------------
                # UPDATE (single item)
                # ----------------------------
                item_id = _safe_str(body.get("id"), 80)
                if not item_id:
                    return send_json(self, 400, {"ok": False, "error": "Missing id"})

                shelf_section = _safe_str(body.get("shelf_section"), 60) if ("shelf_section" in body) else None
                shelf_slot = body.get("shelf_slot", None) if ("shelf_slot" in body) else None
                accent = _safe_str(body.get("accent"), 24) if ("accent" in body) else None
                notes = _safe_str(body.get("notes"), 2000) if ("notes" in body) else None
                premium_pct = _num(body.get("premium_pct")) if ("premium_pct" in body) else None
                qty = body.get("qty", None) if ("qty" in body) else None

                if shelf_section is not None and shelf_section.strip() == "":
                    shelf_section = "Main"

                if shelf_slot is not None:
                    try:
                        shelf_slot = int(shelf_slot)
                    except Exception:
                        return send_json(self, 400, {"ok": False, "error": "Invalid shelf_slot"})
                    shelf_slot = _clamp(shelf_slot, 0, 999999)

                if premium_pct is not None and (premium_pct < 0 or premium_pct > 500):
                    return send_json(self, 400, {"ok": False, "error": "premium_pct out of range (0–500)"})

                if qty is not None:
                    try:
                        qty = int(qty)
                    except Exception:
                        return send_json(self, 400, {"ok": False, "error": "Invalid qty"})
                    qty = _clamp(qty, 1, 100000)

                sets = []
                vals = []

                if shelf_section is not None:
                    sets.append("shelf_section = %s")
                    vals.append(shelf_section)

                if ("shelf_slot" in body):
                    sets.append("shelf_slot = %s")
                    vals.append(shelf_slot if shelf_slot is not None else None)

                if accent is not None:
                    sets.append("accent = %s")
                    vals.append(accent)

                if notes is not None:
                    sets.append("notes = %s")
                    vals.append(notes)

                if ("premium_pct" in body):
                    sets.append("premium_pct = %s")
                    vals.append(float(premium_pct) if premium_pct is not None else None)

                if ("qty" in body):
                    sets.append("qty = %s")
                    vals.append(qty if qty is not None else 1)

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

    def log_message(self, *_):
        return
