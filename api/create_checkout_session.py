from http.server import BaseHTTPRequestHandler
import json
import os

import stripe

try:
    from ._utils import send_json
except Exception:
    from api._utils import send_json


def _env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise ValueError(f"Missing env var: {name}")
    return v


def _norm_interval(raw: str) -> str:
    v = (raw or "").strip().lower()
    if v in ("month", "monthly", "mo", "m"):
        return "monthly"
    if v in ("year", "yearly", "annual", "yr", "y"):
        return "yearly"
    return ""


PRICE_ENV = {
    ("pro", "monthly"): "STRIPE_PRICE_ID_PRO_MONTHLY",
    ("pro", "yearly"): "STRIPE_PRICE_ID_PRO_YEARLY",
    ("elite", "monthly"): "STRIPE_PRICE_ID_ELITE_MONTHLY",
    ("elite", "yearly"): "STRIPE_PRICE_ID_ELITE_YEARLY",
}


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            stripe.api_key = _env("STRIPE_SECRET_KEY")

            length = int(self.headers.get("content-length", "0") or "0")
            raw = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            payload = json.loads(raw or "{}")

            plan = (payload.get("plan") or "").strip().lower()
            if plan not in ("pro", "elite"):
                return send_json(self, 400, {"ok": False, "error": "Invalid plan. Use 'pro' or 'elite'."})

            interval = _norm_interval(payload.get("interval") or payload.get("billing") or "")
            if interval not in ("monthly", "yearly"):
                return send_json(self, 400, {"ok": False, "error": "Invalid interval. Use 'monthly' or 'yearly'."})

            env_name = PRICE_ENV[(plan, interval)]
            price_id = _env(env_name)

            success_url = _env("STRIPE_SUCCESS_URL")
            cancel_url = _env("STRIPE_CANCEL_URL")

            session = stripe.checkout.Session.create(
                mode="subscription",
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=success_url,
                cancel_url=cancel_url,
                allow_promotion_codes=True,
                metadata={"plan": plan, "interval": interval},
            )

            return send_json(self, 200, {"ok": True, "url": session.get("url")})

        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": str(e)})

    def do_GET(self):
        return send_json(self, 405, {"ok": False, "error": "Use POST"})

    def log_message(self, format, *args):
        return
