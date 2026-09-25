import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def _bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float(key: str, default: float) -> float:
    raw = os.getenv(key)
    try:
        return float(raw) if raw not in (None, "") else default
    except ValueError:
        return default


def _int(key: str, default: int) -> int:
    raw = os.getenv(key)
    try:
        return int(raw) if raw not in (None, "") else default
    except ValueError:
        return default


CURRENCY = os.getenv("CURRENCY", "EUR").upper()
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/trader.db")

RISK_MULTIPLIER = _float("RISK_MULTIPLIER", 2.0)
RISK_WINDOW_DAYS = _int("RISK_WINDOW_DAYS", 30)
PRICE_FRESHNESS_HOURS = _int("PRICE_FRESHNESS_HOURS", 24)
STEAM_SALE_FEE = _float("STEAM_SALE_FEE", 0.15)
MIN_SELL_MARGIN_PCT = _float("MIN_SELL_MARGIN_PCT", 2.0)

STEAM_MAX_PER_RUN = _int("STEAM_MAX_PER_RUN", 20)
CSFLOAT_MAX_PER_RUN = _int("CSFLOAT_MAX_PER_RUN", 25)

STEAM_COOKIES = os.getenv("STEAM_COOKIES", "")
CSFLOAT_API_KEY = os.getenv("CSFLOAT_API_KEY", "")
SKINPORT_API_KEY = os.getenv("SKINPORT_API_KEY", "")
DMARKET_PUBLIC_KEY = os.getenv("DMARKET_PUBLIC_KEY", "")
DMARKET_SECRET_KEY = os.getenv("DMARKET_SECRET_KEY", "")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
NOTIFY_MIN_EV = _float("NOTIFY_MIN_EV", 10.0)

LMSTUDIO_ENABLED = _bool("LMSTUDIO_ENABLED", False)
LMSTUDIO_BASE_URL = os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
LMSTUDIO_MODEL = os.getenv("LMSTUDIO_MODEL", "local-model")

RUN_SCHEDULER = _bool("RUN_SCHEDULER", True)


def setup_logging(level: str | None = None) -> None:
    level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            '{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for noisy in ("urllib3", "apscheduler"):
        logging.getLogger(noisy).setLevel("WARNING")
