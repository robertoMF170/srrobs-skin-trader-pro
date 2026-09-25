import logging
import time
from dataclasses import dataclass

import requests

import db

log = logging.getLogger(__name__)


@dataclass
class PricePoint:
    market_hash_name: str
    source: str
    price: float
    float_value: float | None = None
    currency: str = ""


class BaseCollector:
    source = "base"
    base_url = ""
    min_interval = 1.0
    timeout = 20
    max_per_run = 100

    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "SrRobsSkinTraderPro/1.0 (+local)"
        self._last_request = 0.0

    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)

    def get(self, url: str, params: dict | None = None,
            headers: dict | None = None, retry_429: bool = True
            ) -> requests.Response | None:
        for attempt in range(1, 5):
            self._throttle()
            self._last_request = time.monotonic()
            try:
                resp = self.session.get(
                    url, params=params, headers=headers, timeout=self.timeout
                )
                if resp.status_code == 429:
                    if not retry_429:
                        log.warning("source=%s status=429 (sem retry)", self.source)
                        return None
                    delay = min(60.0, 5.0 * (2 ** attempt))
                    log.warning(
                        "source=%s status=429 a aguardar %.0fs", self.source, delay
                    )
                    time.sleep(delay)
                    continue
                if resp.status_code >= 500:
                    log.warning("source=%s status=%d tentativa=%d",
                                self.source, resp.status_code, attempt)
                    time.sleep(2.0 * attempt)
                    continue
                resp.raise_for_status()
                return resp
            except requests.RequestException as exc:
                log.warning("source=%s erro=%s tentativa=%d",
                            self.source, exc, attempt)
                time.sleep(min(30.0, 2.0 * (2 ** (attempt - 1))))
        log.error("source=%s falhou após retries url=%s", self.source, url)
        return None

    def collect(self, names: list[str], conn=None) -> list[PricePoint]:
        raise NotImplementedError

    def collect_and_store(self, names: list[str]) -> int:
        points = []
        try:
            points = self.collect(names)
        except Exception:
            log.exception("source=%s coleção falhou", self.source)
        if not points:
            return 0
        with db.connect() as conn:
            for p in points:
                db.record_price(
                    conn,
                    market_hash_name=p.market_hash_name,
                    source=p.source,
                    price=p.price,
                    currency=p.currency or None,
                    float_value=p.float_value,
                )
        log.info("source=%s gravados=%d", self.source, len(points))
        return len(points)
