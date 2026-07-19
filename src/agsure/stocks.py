from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping


@dataclass(frozen=True)
class StockComparison:
    reference_period: str
    latest_tonnes: Decimal
    year_over_year_pct: Decimal | None
    five_year_average_tonnes: Decimal | None
    five_year_deviation_pct: Decimal | None
    baseline_periods: tuple[str, ...]


def _pct_change(current: Decimal, baseline: Decimal) -> Decimal | None:
    if baseline == 0:
        return None
    return (current - baseline) / baseline * Decimal("100")


def compare_same_snapshot(
    observations: Mapping[str, Decimal | None], baseline_years: int = 5
) -> StockComparison:
    """Compare the latest value only with the same snapshot in prior years."""
    if baseline_years < 1:
        raise ValueError("baseline_years must be at least 1")
    available = {
        period: value for period, value in observations.items() if value is not None
    }
    if not available:
        raise ValueError("At least one published stock observation is required")
    months = {period[5:7] for period in observations}
    if len(months) != 1:
        raise ValueError("Stock comparisons must contain one snapshot period")

    latest_period = max(available)
    latest_value = available[latest_period]
    latest_year, month = latest_period.split("-")
    year = int(latest_year)
    prior_period = f"{year - 1:04d}-{month}"
    prior_value = observations.get(prior_period)
    year_over_year = (
        None if prior_value is None else _pct_change(latest_value, prior_value)
    )

    baseline_periods = tuple(
        f"{baseline_year:04d}-{month}"
        for baseline_year in range(year - baseline_years, year)
    )
    baseline_values = [observations.get(period) for period in baseline_periods]
    if any(value is None for value in baseline_values):
        average = None
        deviation = None
    else:
        complete_values = [value for value in baseline_values if value is not None]
        average = sum(complete_values, Decimal("0")) / Decimal(baseline_years)
        deviation = _pct_change(latest_value, average)

    return StockComparison(
        reference_period=latest_period,
        latest_tonnes=latest_value,
        year_over_year_pct=year_over_year,
        five_year_average_tonnes=average,
        five_year_deviation_pct=deviation,
        baseline_periods=baseline_periods,
    )
