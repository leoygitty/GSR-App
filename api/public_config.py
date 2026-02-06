from http.server import BaseHTTPRequestHandler
import os
try:
    from ._utils import send_json
except Exception:
    from api._utils import send_json

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        pk = (os.environ.get("CLERK_PUBLISHABLE_KEY") or "").strip()
        if not pk:
            return send_json(self, 500, {"ok": False, "error": "Missing CLERK_PUBLISHABLE_KEY"})
        return send_json(self, 200, {"ok": True, "clerk_publishable_key": pk})

    def log_message(self, *_):
        return
