import logging
import re
from datetime import datetime, timezone

import config
from collectors.base import BaseCollector, PricePoint

log = logging.getLogger(__name__)

CURRENCY_CODES = {"USD": 1, "GBP": 2, "EUR": 3, "BRL": 7, "PLN": 6, "CAD": 20}

PRICE_RE = re.compile(r"[0-9][0-9.,\s]*[0-9]")


def parse_steam_price(raw: str) -> float | None:
    match = PRICE_RE.search(raw or "")
    if not match:
        return None
    token = match.group(0).replace(" ", "")
    if "," in token and "." in token:
        token = token.replace(".", "") if token.rfind(",") > token.rfind(".") \
            else token.replace(",", "")
    token = token.replace(",", ".")
    try:
        return float(token)
    except ValueError:
        return None


class SteamCollector(BaseCollector):
    source = "steam"
    base_url = "https://steamcommunity.com/market"

    def __init__(self):
        super().__init__()
        self.min_interval = 3.5
        self.max_per_run = config.STEAM_MAX_PER_RUN
        self.currency_code = CURRENCY_CODES.get(config.CURRENCY, 1)
        if config.STEAM_COOKIES:
            self.session.headers["Cookie"] = config.STEAM_COOKIES

    def _priceoverview(self, name: str) -> PricePoint | None:
        resp = self.get(
            f"{self.base_url}/priceoverview/",
            params={
                "appid": 730,
                "currency": self.currency_code,
                "market_hash_name": name,
            },
            retry_429=False,
        )
        if resp is None:
            return None
        try:
            data = resp.json()
        except ValueError:
            return None
        if not data.get("success"):
            return None
        price = parse_steam_price(
            data.get("lowest_price") or data.get("median_price") or ""
        )
        if price is None:
            return None
        return PricePoint(
            market_hash_name=name,
            source=self.source,
            price=price,
            currency=config.CURRENCY,
        )

    def collect(self, names: list[str], conn=None) -> list[PricePoint]:
        points: list[PricePoint] = []
        consecutive_failures = 0
        for name in names[: self.max_per_run]:
            point = self._priceoverview(name)
            if point:
                points.append(point)
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                if consecutive_failures >= 5:
                    log.error(
                        "source=steam 5 falhas consecutivas — IP provavelmente "
                        "limitado (429) ou cookies em falta; run abortado"
                    )
                    break
        return points

    def _pricehistory(self, name: str) -> list[tuple[str, float]]:
        resp = self.get(
            f"{self.base_url}/pricehistory/",
            params={"appid": 730, "market_hash_name": name},
            retry_429=False,
        )
        if resp is None:
            return []
        try:
            data = resp.json()
        except ValueError:
            return []
        if not data.get("success") or not data.get("prices"):
            return []
        out = []
        for row in data["prices"]:
            try:
                ts = datetime.strptime(row[0], "%b %d %Y %H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
                out.append((ts.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), float(row[1])))
            except (ValueError, IndexError):
                continue
        return out
