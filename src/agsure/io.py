from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

from agsure.models import CropYearObservation


REQUIRED_FIELDS = {
    "commodity",
    "crop_year",
    "seeded_area_kha",
    "harvested_area_kha",
    "yield_t_ha",
    "production_kt",
    "carryout_kt",
    "total_use_kt",
    "precip_pct_normal",
    "gdd_pct_normal",
    "status",
}


def load_observations(path: str | Path) -> list[CropYearObservation]:
    observations: list[CropYearObservation] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_FIELDS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")

        for row_number, row in enumerate(reader, start=2):
            try:
                observation = CropYearObservation(
                    commodity=row["commodity"].strip().lower(),
                    crop_year=int(row["crop_year"]),
                    seeded_area_kha=Decimal(row["seeded_area_kha"]),
                    harvested_area_kha=Decimal(row["harvested_area_kha"]),
                    yield_t_ha=Decimal(row["yield_t_ha"]),
                    production_kt=Decimal(row["production_kt"]),
                    carryout_kt=Decimal(row["carryout_kt"]),
                    total_use_kt=Decimal(row["total_use_kt"]),
                    precip_pct_normal=Decimal(row["precip_pct_normal"]),
                    gdd_pct_normal=Decimal(row["gdd_pct_normal"]),
                    status=row["status"].strip().lower(),
                )
            except (KeyError, ValueError) as exc:
                raise ValueError(f"Invalid row {row_number}: {exc}") from exc
            observations.append(observation)

    keys = [(item.commodity, item.crop_year) for item in observations]
    if len(keys) != len(set(keys)):
        raise ValueError("Each commodity and crop_year pair must be unique")
    return sorted(observations, key=lambda item: (item.commodity, item.crop_year))
