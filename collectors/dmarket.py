import base64
import logging

import config
from collectors.base import BaseCollector, PricePoint

log = logging.getLogger(__name__)

API_HOST = "https://api.dmarket.com"
CS2_GAME_ID = "a8db"


class DmarketCollector(BaseCollector):
    source = "dmarket"
    path = "/marketplace-api/v2/offers"

    def __init__(self):
        super().__init__()
        self.min_interval = 1.2
        self.max_per_run = 60

    def _auth_header(self) -> str:
        raw = f"{config.DMARKET_PUBLIC_KEY}:{config.DMARKET_SECRET_KEY}"
        return "Basic " + base64.b64encode(raw.encode()).decode()

    def _cheapest(self, name: str) -> PricePoint | None:
        resp = self.get(
            f"{API_HOST}{self.path}",
            params={
                "game_id": CS2_GAME_ID,
                "side": "market",
                "orderBy": "price",
                "orderDir": "asc",
                "title": name,
                "limit": 20,
            },
            headers={"Authorization": self._auth_header()},
            retry_429=False,
        )
        if resp is None:
            return None
        try:
            data = resp.json()
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
        if resp.status_code in (401, 403):
            log.error(
                "source=dmarket auth falhou (%s) — verifica DMARKET_PUBLIC_KEY/"
                "DMARKET_SECRET_KEY no .env (dmarket.com → definições → API keys)",
                data.get("Message", resp.status_code),
            )
            return None
        objects = data.get("objects") or []
        for obj in objects:
            title = obj.get("title") or obj.get("marketHashName") or ""
            if title != name:
                continue
            price_block = obj.get("price") or {}
            raw = price_block.get("USD") or price_block.get(config.CURRENCY)
            if raw is None:
                continue
            try:
                price = float(raw) / 100.0
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            return PricePoint(
                market_hash_name=name,
                source=self.source,
                price=price,
                currency="USD",
            )
        return None

    def collect(self, names: list[str], conn=None) -> list[PricePoint]:
        if not config.DMARKET_PUBLIC_KEY or not config.DMARKET_SECRET_KEY:
            log.warning(
                "source=dmarket chaves não configuradas — gera em dmarket.com "
                "(definições → API) e define DMARKET_PUBLIC_KEY/DMARKET_SECRET_KEY no .env"
            )
            return []
        points: list[PricePoint] = []
        consecutive_failures = 0
        for name in names[: self.max_per_run]:
            point = self._cheapest(name)
            if point:
                points.append(point)
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                if consecutive_failures >= 5:
                    log.error("source=dmarket 5 falhas consecutivas — run abortada")
                    break
        return points
