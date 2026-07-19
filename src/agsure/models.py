from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CropYearObservation:
    commodity: str
    crop_year: int
    seeded_area_kha: Decimal
    harvested_area_kha: Decimal
    yield_t_ha: Decimal
    production_kt: Decimal
    carryout_kt: Decimal
    total_use_kt: Decimal
    precip_pct_normal: Decimal
    gdd_pct_normal: Decimal
    status: str

    @property
    def stocks_to_use_pct(self) -> Decimal:
        if self.total_use_kt <= 0:
            raise ValueError("total_use_kt must be greater than zero")
        return self.carryout_kt / self.total_use_kt * Decimal("100")


@dataclass(frozen=True)
class ScoreComponent:
    name: str
    current: Decimal
    baseline: Decimal
    deviation_pct: Decimal
    weight: Decimal
    contribution: Decimal


@dataclass(frozen=True)
class SupplyPressureResult:
    crop_year: int
    score: Decimal
    classification: str
    components: tuple[ScoreComponent, ...]
    observation_status: str
