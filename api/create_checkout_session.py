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


def _normalize_interval(raw: str) -> str:
    s = (raw or "").strip().lower()
    if s in ("year", "annual", "annually", "yr"):
        return "yearly"
    if s in ("month", "monthly", "mo"):
        return "monthly"
    # default
    return "monthly"


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

            interval = _normalize_interval(payload.get("interval"))
            if interval not in ("monthly", "yearly"):
                interval = "monthly"

            # ENV VARS YOU SAID YOU CREATED:
            # STRIPE_PRICE_ID_PRO_MONTHLY
            # STRIPE_PRICE_ID_PRO_YEARLY
            # STRIPE_PRICE_ID_ELITE_MONTHLY
            # STRIPE_PRICE_ID_ELITE_YEARLY
            price_env = f"STRIPE_PRICE_ID_{plan.upper()}_{interval.upper()}"
            price_id = _env(price_env)

            success_url = _env("STRIPE_SUCCESS_URL")
            cancel_url = _env("STRIPE_CANCEL_URL")

            session = stripe.checkout.Session.create(
                mode="subscription",
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=success_url,
                cancel_url=cancel_url,
                allow_promotion_codes=True,
                # helpful later for webhooks + tier logic
                metadata={"plan": plan, "interval": interval},
            )

            return send_json(self, 200, {"ok": True, "url": session.get("url")})

        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": str(e)})

    def do_GET(self):
        return send_json(self, 405, {"ok": False, "error": "Use POST"})

    def log_message(self, format, *args):
        return
