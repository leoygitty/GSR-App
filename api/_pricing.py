import json
from decimal import Decimal
from typing import Dict, Tuple
from urllib.request import Request, urlopen


GOLD_API_XAU = "https://api.gold-api.com/price/XAU"
GOLD_API_XAG = "https://api.gold-api.com/price/XAG"


def _fetch_json(url: str) -> Dict:
    req = Request(url, headers={"User-Agent": "gsr-vercel-app/1.0"})
    with urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def fetch_spot_prices_usd() -> Tuple[Decimal, Decimal, Dict, Dict]:
    """Returns (gold_usd, silver_usd, gold_raw, silver_raw)."""
    g = _fetch_json(GOLD_API_XAU)
    s = _fetch_json(GOLD_API_XAG)

    # gold-api commonly returns a JSON with a 'price' field.
    # Keep this resilient in case the shape changes.
    def price_of(obj: Dict) -> Decimal:
        for key in ("price", "value", "rate", "usd"):
            if key in obj:
                return Decimal(str(obj[key]))
        raise ValueError(f"Unsupported pricing payload (missing price-like field): {obj.keys()}")

    return price_of(g), price_of(s), g, s
