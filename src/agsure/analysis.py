from __future__ import annotations

from decimal import Decimal
from statistics import fmean

from agsure.commodities import get_commodity
from agsure.models import (
    CropYearObservation,
    ScoreComponent,
    SupplyPressureResult,
)


WEIGHTS = {
    "production": Decimal("0.40"),
    "carryout": Decimal("0.25"),
    "stocks_to_use": Decimal("0.20"),
    "precipitation": Decimal("0.10"),
    "growing_degree_days": Decimal("0.05"),
}


def _mean(values: list[Decimal]) -> Decimal:
    if not values:
        raise ValueError("Cannot calculate a baseline from no observations")
    return Decimal(str(fmean(float(value) for value in values)))


def _deviation(current: Decimal, baseline: Decimal) -> Decimal:
    if baseline == 0:
        raise ValueError("Baseline must not be zero")
    return (current - baseline) / baseline * Decimal("100")


def _component(
    name: str,
    current: Decimal,
    baseline: Decimal,
    weight: Decimal,
    *,
    already_percent_of_normal: bool = False,
) -> ScoreComponent:
    deviation = current - Decimal("100") if already_percent_of_normal else _deviation(current, baseline)
    return ScoreComponent(
        name=name,
        current=current,
        baseline=baseline,
        deviation_pct=deviation,
        weight=weight,
        contribution=deviation * weight,
    )


def classify_score(score: Decimal) -> str:
    if score < 30:
        return "tight"
    if score < 45:
        return "moderately tight"
    if score <= 55:
        return "balanced"
    if score <= 70:
        return "moderately abundant"
    return "abundant"


def calculate_supply_pressure(
    observations: list[CropYearObservation], baseline_years: int = 5
) -> SupplyPressureResult:
    if baseline_years < 2:
        raise ValueError("baseline_years must be at least 2")
    if len(observations) < baseline_years + 1:
        raise ValueError(
            f"At least {baseline_years + 1} observations are required for a "
            f"{baseline_years}-year baseline"
        )

    commodity_slugs = {item.commodity for item in observations}
    if len(commodity_slugs) != 1:
        raise ValueError("Supply-pressure inputs must contain exactly one commodity")
    commodity = get_commodity(next(iter(commodity_slugs)))
    if not commodity.score_model_enabled:
        raise ValueError(
            f"The supply-pressure model is not yet validated for {commodity.display_name}"
        )

    ordered = sorted(observations, key=lambda item: item.crop_year)
    current = ordered[-1]
    baseline = ordered[-(baseline_years + 1) : -1]

    components = (
        _component(
            "production",
            current.production_kt,
            _mean([item.production_kt for item in baseline]),
            WEIGHTS["production"],
        ),
        _component(
            "carryout",
            current.carryout_kt,
            _mean([item.carryout_kt for item in baseline]),
            WEIGHTS["carryout"],
        ),
        _component(
            "stocks_to_use",
            current.stocks_to_use_pct,
            _mean([item.stocks_to_use_pct for item in baseline]),
            WEIGHTS["stocks_to_use"],
        ),
        _component(
            "precipitation",
            current.precip_pct_normal,
            Decimal("100"),
            WEIGHTS["precipitation"],
            already_percent_of_normal=True,
        ),
        _component(
            "growing_degree_days",
            current.gdd_pct_normal,
            Decimal("100"),
            WEIGHTS["growing_degree_days"],
            already_percent_of_normal=True,
        ),
    )

    raw_score = Decimal("50") + sum(
        (item.contribution for item in components), start=Decimal("0")
    )
    score = min(Decimal("100"), max(Decimal("0"), raw_score))
    score = score.quantize(Decimal("0.1"))

    return SupplyPressureResult(
        crop_year=current.crop_year,
        score=score,
        classification=classify_score(score),
        components=components,
        observation_status=current.status,
    )
