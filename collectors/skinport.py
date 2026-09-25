import logging

import config
from collectors.base import BaseCollector, PricePoint

log = logging.getLogger(__name__)


class SkinportCollector(BaseCollector):
    source = "skinport"
    base_url = "https://api.skinport.com/v1/items"

    def __init__(self):
        super().__init__()
        self.min_interval = 45.0
        self.max_per_run = 100000

    def collect(self, names: list[str], conn=None) -> list[PricePoint]:
        headers = {}
        if config.SKINPORT_API_KEY:
            headers["Authorization"] = f"Bearer {config.SKINPORT_API_KEY}"
        resp = self.get(
            self.base_url,
            params={"app_id": 730, "currency": config.CURRENCY},
            headers=headers or None,
        )
        if resp is None:
            return []
        try:
            items = resp.json()
        except ValueError:
            return []
        wanted = set(names)
        points: list[PricePoint] = []
        for item in items:
            name = item.get("market_hash_name")
            if name not in wanted:
                continue
            currency = item.get("currency", config.CURRENCY)
            min_price = item.get("min_price")
            if min_price not in (None, ""):
                try:
                    price = float(min_price)
                    if price > 0:
                        points.append(
                            PricePoint(
                                market_hash_name=name,
                                source=self.source,
                                price=price,
                                currency=currency,
                            )
                        )
                except (TypeError, ValueError):
                    pass
            suggested = item.get("suggested_price")
            if suggested not in (None, ""):
                try:
                    ref_price = float(suggested)
                    if ref_price > 0:
                        points.append(
                            PricePoint(
                                market_hash_name=name,
                                source="steam_ref",
                                price=ref_price,
                                currency=currency,
                            )
                        )
                except (TypeError, ValueError):
                    pass
        return points
