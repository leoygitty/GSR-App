from http.server import BaseHTTPRequestHandler
import json
import os

import stripe

try:
    from ._utils import send_json
except Exception:
    from api._utils import send_json


def _env(name: str, allow_empty: bool = False) -> str:
    v = os.environ.get(name, "").strip()
    if not v and not allow_empty:
        raise ValueError(f"Missing env var: {name}")
    return v


def _price_for_plan(plan: str) -> str:
    """
    Prefer new env var names (matches _utils.py):
      - STRIPE_PRICE_PRO
      - STRIPE_PRICE_ELITE

    Backward compatible with your older names:
      - STRIPE_PRICE_ID_PRO
      - STRIPE_PRICE_ID_ELITE
    """
    if plan == "pro":
        return (
            os.environ.get("STRIPE_PRICE_PRO", "").strip()
            or os.environ.get("STRIPE_PRICE_ID_PRO", "").strip()
        )
    if plan == "elite":
        return (
            os.environ.get("STRIPE_PRICE_ELITE", "").strip()
            or os.environ.get("STRIPE_PRICE_ID_ELITE", "").strip()
        )
    return ""


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

            price_id = _price_for_plan(plan)
            if not price_id:
                return send_json(self, 500, {"ok": False, "error": f"Missing price id env var for plan '{plan}'."})

            # Optional email (used later for mapping user -> tier)
            email = (payload.get("email") or "").strip().lower()
            if email and ("@" not in email or "." not in email):
                return send_json(self, 400, {"ok": False, "error": "Invalid email."})

            success_url = _env("STRIPE_SUCCESS_URL")
            cancel_url = _env("STRIPE_CANCEL_URL")

            session = stripe.checkout.Session.create(
                mode="subscription",
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=success_url,
                cancel_url=cancel_url,
                allow_promotion_codes=True,

                # Helps webhook + later login flow
                customer_email=email or None,

                # Store tier info in session + subscription metadata
                metadata={"tier": plan, "price_id": price_id, "email": email or ""},
                subscription_data={"metadata": {"tier": plan, "price_id": price_id, "email": email or ""}},
            )

            return send_json(self, 200, {"ok": True, "url": session.get("url")})

        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": str(e)})

    def do_GET(self):
        return send_json(self, 405, {"ok": False, "error": "Use POST"})

    def log_message(self, format, *args):
        return
