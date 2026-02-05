from http.server import BaseHTTPRequestHandler
import json
import os

try:
    from ._utils import send_json
except Exception:
    from api._utils import send_json


def _env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise ValueError(f"Missing env var: {name}")
    return v


def _price_env_key(plan: str, interval: str) -> str:
    plan = plan.upper()
    interval = interval.upper()
    return f"STRIPE_PRICE_ID_{plan}_{interval}"


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            # ✅ import stripe inside handler so import errors return JSON (not Vercel generic 500)
            import stripe

            stripe.api_key = _env("STRIPE_SECRET_KEY")

            length = int(self.headers.get("content-length", "0") or "0")
            raw = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            payload = json.loads(raw or "{}")

            plan = (payload.get("plan") or "").strip().lower()
            interval = (payload.get("interval") or "").strip().lower()  # monthly | yearly

            if plan not in ("pro", "elite"):
                return send_json(self, 400, {"ok": False, "error": "Invalid plan. Use 'pro' or 'elite'."})

            if interval not in ("monthly", "yearly"):
                return send_json(self, 400, {"ok": False, "error": "Invalid interval. Use 'monthly' or 'yearly'."})

            # Your new env vars:
            # STRIPE_PRICE_ID_PRO_MONTHLY, STRIPE_PRICE_ID_PRO_YEARLY
            # STRIPE_PRICE_ID_ELITE_MONTHLY, STRIPE_PRICE_ID_ELITE_YEARLY
            price_id = _env(_price_env_key(plan, interval))

            success_url = _env("STRIPE_SUCCESS_URL")
            cancel_url = _env("STRIPE_CANCEL_URL")

            # Optional: pass customer email if you want
            email = (payload.get("email") or "").strip()
            create_kwargs = {}
            if email:
                create_kwargs["customer_email"] = email

            session = stripe.checkout.Session.create(
                mode="subscription",
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=success_url,
                cancel_url=cancel_url,
                allow_promotion_codes=True,
                metadata={"plan": plan, "interval": interval},
                **create_kwargs,
            )

            return send_json(self, 200, {"ok": True, "url": session.get("url")})

        except Exception as e:
            # ✅ Now you’ll actually see the real error as JSON
            return send_json(self, 500, {"ok": False, "error": str(e)})

    def do_GET(self):
        return send_json(self, 405, {"ok": False, "error": "Use POST"})

    def log_message(self, format, *args):
        return
