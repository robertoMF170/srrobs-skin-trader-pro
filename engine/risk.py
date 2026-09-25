"""Motor de risco: volatilidade histórica por skin e classificação de robustez."""

from __future__ import annotations

import math

import db

MIN_POINTS = 3
MIN_COVERAGE = 0.5


def stddev(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(variance)


def price_stddev(
    conn, market_hash_name: str, days: int = 30, source: str | None = None
) -> tuple[float, int]:
    """σ diária: reduz a série à última leitura de cada dia antes de calcular."""
    series = db.price_series(conn, market_hash_name, days=days, source=source)
    daily: dict[str, float] = {}
    for ts, price in series:
        daily[ts[:10]] = price
    prices = list(daily.values())
    if len(prices) < MIN_POINTS:
        return 0.0, len(prices)
    return stddev(prices), len(prices)


def distribution_risk(conn, distribution: list[dict], days: int = 30) -> tuple[float, float]:
    """Retorna (desvio-padrão ponderado, cobertura de dados históricos)."""
    weighted = 0.0
    coverage = 0.0
    for d in distribution:
        sd, n = price_stddev(conn, d["name"], days=days)
        weighted += d["prob"] * sd
        if n >= MIN_POINTS:
            coverage += d["prob"]
    return weighted, min(coverage, 1.0)


def classify(
    ev_net: float,
    risk_sd: float,
    multiplier: float,
    coverage: float = 1.0,
    min_coverage: float = MIN_COVERAGE,
) -> dict:
    enough_data = coverage >= min_coverage
    robust = bool(
        ev_net > 0
        and enough_data
        and (risk_sd <= 0 or ev_net >= multiplier * risk_sd)
    )
    return {
        "risk_sd": round(risk_sd, 2),
        "risk_coverage": round(coverage, 3),
        "enough_data": enough_data,
        "robust": robust,
        "robust_rule": f"EV ≥ {multiplier}× σ ({days_window_note()})",
    }


def days_window_note() -> str:
    import config

    return f"{config.RISK_WINDOW_DAYS}d"
