import logging

import config
from collectors.base import BaseCollector, PricePoint

log = logging.getLogger(__name__)


class CsfloatCollector(BaseCollector):
    source = "csfloat"
    base_url = "https://csfloat.com/api/v1/listings"

    def __init__(self):
        super().__init__()
        self.min_interval = 1.2
        self.max_per_run = config.CSFLOAT_MAX_PER_RUN

    def _headers(self) -> dict:
        if config.CSFLOAT_API_KEY:
            return {"Authorization": config.CSFLOAT_API_KEY}
        return {}

    def _listings(self, name: str) -> PricePoint | None:
        resp = self.get(
            self.base_url,
            params={
                "market_hash_name": name,
                "sort_by": "lowest_price",
                "category": 1,
                "limit": 5,
            },
            headers=self._headers() or None,
            retry_429=False,
        )
        if resp is None:
            return None
        try:
            listings = resp.json()
        except ValueError:
            return None
        if isinstance(listings, dict):
            msg = listings.get("message", "")
            if resp.status_code in (401, 403) or "logged in" in msg:
                log.error(
                    "source=csfloat exige chave de API (csfloat.com → perfil → "
                    "separador developer). msg=%s", msg,
                )
            return None
        if not isinstance(listings, list) or not listings:
            return None
        best = listings[0]
        price = best.get("price")
        if price is None:
            return None
        float_value = (best.get("item") or {}).get("float_value")
        return PricePoint(
            market_hash_name=name,
            source=self.source,
            price=float(price) / 100.0,
            float_value=float(float_value) if float_value is not None else None,
            currency="USD",
        )

    def collect(self, names: list[str], conn=None) -> list[PricePoint]:
        if not config.CSFLOAT_API_KEY:
            log.warning(
                "source=csfloat CSFLOAT_API_KEY não configurada — cria a chave "
                "grátis em csfloat.com (perfil → developer) e define no .env"
            )
            return []
        points: list[PricePoint] = []
        consecutive_failures = 0
        for name in names[: self.max_per_run]:
            point = self._listings(name)
            if point:
                points.append(point)
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                if consecutive_failures >= 5:
                    log.error("source=csfloat 5 falhas consecutivas — run abortada")
                    break
        return points
