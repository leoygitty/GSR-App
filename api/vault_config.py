from http.server import BaseHTTPRequestHandler
import json
import os

try:
    from ._utils import send_json
except Exception:
    from api._utils import send_json


def _env(name: str, default: str = ""):
    v = (os.environ.get(name) or "").strip()
    return v if v else default


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Premium-ready config: the UI can render a "shelf" even before entitlements exist.
        config = {
            "ok": True,
            "brand": {
                "name": "MetalMetric",
                "theme": "vault",
            },
            "shelf": {
                "sections": [
                    {"key": "Main", "label": "Main Shelf", "cols": 6, "rows": 3},
                    {"key": "Coins", "label": "Coin Tray", "cols": 8, "rows": 2},
                    {"key": "Jewelry", "label": "Jewelry Case", "cols": 5, "rows": 2},
                ],
                "accents": [
                    {"key": "gold", "label": "Gold", "glow": "rgba(245,200,90,.22)"},
                    {"key": "silver", "label": "Silver", "glow": "rgba(210,220,232,.18)"},
                    {"key": "plat", "label": "Platinum", "glow": "rgba(180,195,255,.18)"},
                    {"key": "blue", "label": "Ice", "glow": "rgba(142,200,255,.22)"},
                ],
            },
            # Premium “templates” (upsell + fast add)
            "templates": [
                {
                    "id": "t_coin_eagle",
                    "label": "1 oz Gold Eagle",
                    "metal": "gold",
                    "item_type": "coin",
                    "weight_value": 1,
                    "weight_unit": "oz",
                    "purity": 0.9167,
                    "accent": "gold",
                    "shelf_section": "Coins",
                },
                {
                    "id": "t_bar_silver_10oz",
                    "label": "10 oz Silver Bar",
                    "metal": "silver",
                    "item_type": "bar",
                    "weight_value": 10,
                    "weight_unit": "oz",
                    "purity": 0.999,
                    "accent": "silver",
                    "shelf_section": "Main",
                },
                {
                    "id": "t_jewelry_14k_ring",
                    "label": "14k Ring",
                    "metal": "gold",
                    "item_type": "jewelry",
                    "weight_value": 5,
                    "weight_unit": "g",
                    "purity": 0.585,
                    "accent": "gold",
                    "shelf_section": "Jewelry",
                },
            ],
            "entitlements": {
                # stub: later you’ll return real tier + flags
                "tier": "free",
                "features": {
                    "virtual_shelf": True,       # show shelf UI
                    "images": False,             # Pro unlock (thumbnails)
                    "history": False,            # Pro unlock
                    "alerts": False,             # Elite unlock
                },
            },
        }

        return send_json(self, 200, config)

    def log_message(self, *_):
        return
