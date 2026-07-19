"""Presentation-ready unified commodity overview built from local artifacts.

This module deliberately has no Streamlit or pandas dependency.  It validates
the normalized artifact contracts, keeps source identities separate, and
returns immutable values that a dashboard (or another client) can render.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping, Sequence

from agsure.commodities import COMMODITIES
from agsure.stocks import StockComparison, compare_same_snapshot
from agsure.statcan_supply_disposition import MEASURES
from agsure.stocks_to_use import FORMULA


SUPPORTED_COMMODITIES = tuple(COMMODITIES)
PRODUCTION_TABLE = "32-10-0359-01"
STOCKS_TABLE = "32-10-0007-01"
SUPPLY_TABLE = "32-10-0013-01"
CANADA = "Canada"
UNAVAILABLE = "Not available from the selected official source"
GEOGRAPHIES = (CANADA, "Alberta", "Saskatchewan", "Manitoba")
STOCK_SOURCE_CROPS = {
    "barley": "Barley",
    "canola": "Canola (rapeseed)",
    "durum-wheat": "Wheat, durum",
    "dry-peas": "Peas, dry",
}
SUPPLY_SOURCE_CROPS = {
    "barley": "Barley",
    "canola": "Canola",
    "durum-wheat": "Durum wheat",
    "dry-peas": "Dry peas",
}


@dataclass(frozen=True)
class ArtifactPaths:
    production: Path
    stocks: Path
    supply_disposition: Path
    stocks_to_use: Path


@dataclass(frozen=True)
class DisplayObservation:
    label: str
    value: Decimal | None
    unit: str
    reference_period: str
    crop_year: str
    geography: str
    source_table: str
    source_url: str
    release_date: str
    retrieved_at: str
    publisher: str
    observation_kind: str
    source_label: str
    provenance: Mapping[str, str]


@dataclass(frozen=True)
class SeriesView:
    available: bool
    reason: str
    identity: str
    observations: tuple[DisplayObservation, ...] = ()
    latest: DisplayObservation | None = None
    comparison: StockComparison | None = None


@dataclass(frozen=True)
class UnifiedOverview:
    commodity: str
    geography: str
    geography_options: tuple[str, ...]
    stock_type: str | None
    stock_type_options: tuple[str, ...]
    stock_snapshot: str | None
    stock_snapshot_options: tuple[str, ...]
    supply_measure: str | None
    supply_measure_options: tuple[str, ...]
    supply_snapshot: str | None
    supply_snapshot_options: tuple[str, ...]
    snapshot: tuple[DisplayObservation, ...]
    production: Mapping[str, SeriesView]
    stocks: SeriesView
    supply_disposition: SeriesView
    stocks_to_use: SeriesView
    artifact_errors: Mapping[str, str]


PRODUCTION_FIELDS = {
    "publisher", "source_table", "source_url", "release_date", "retrieved_at",
    "reference_period", "commodity", "source_crop", "geography", "metric",
    "value", "unit",
}
STOCK_FIELDS = {
    "publisher", "source_table", "source_url", "release_date", "retrieved_at",
    "reference_period", "reference_date", "snapshot_period", "commodity",
    "source_crop", "geography", "stock_type", "normalized_tonnes",
    "normalized_unit",
}
SUPPLY_FIELDS = {
    "publisher", "source_table", "source_url", "release_date", "retrieved_at",
    "reference_period", "snapshot_period", "crop_year", "commodity",
    "source_crop", "geography", "measure", "normalized_tonnes",
    "normalized_unit",
}
RATIO_FIELDS = {
    "publisher", "source_table", "source_url", "source_release_date",
    "source_retrieval_date", "reference_period", "snapshot_period", "crop_year",
    "commodity", "source_crop", "geography", "ending_stocks_tonnes",
    "total_use_tonnes", "stocks_to_use_pct", "calculation_status",
    "calculation_reason", "formula", "methodology_version",
}


def _read(path: Path, fields: set[str], name: str) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"{UNAVAILABLE}: local {name} artifact is missing")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = fields - set(reader.fieldnames or ())
        if missing:
            raise ValueError(
                f"{name} artifact is missing required columns: "
                + ", ".join(sorted(missing))
            )
        return [dict(row) for row in reader]


def _decimal(value: str, identity: str) -> Decimal | None:
    if not value.strip():
        return None
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Nonnumeric value for {identity}: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"Nonnumeric value for {identity}: {value!r}")
    return result


def _validate_rows(
    rows: Sequence[Mapping[str, str]],
    *,
    name: str,
    table: str,
    key_fields: tuple[str, ...],
    canada_only: bool = False,
    july_only: bool = False,
    source_crops: Mapping[str, str] | None = None,
) -> None:
    keys: set[tuple[str, ...]] = set()
    for number, row in enumerate(rows, start=2):
        metadata_fields = (
            "publisher",
            "source_url",
            "source_release_date" if name == "stocks_to_use" else "release_date",
            "source_retrieval_date" if name == "stocks_to_use" else "retrieved_at",
            "reference_period",
            "geography",
        )
        missing_metadata = [field for field in metadata_fields if not row[field].strip()]
        if missing_metadata:
            raise ValueError(
                f"{name} row {number} is missing provenance: "
                + ", ".join(missing_metadata)
            )
        if row["source_table"] != table:
            raise ValueError(
                f"{name} row {number} has incompatible source table "
                f"{row['source_table']!r}; expected {table!r}"
            )
        if row["commodity"] not in SUPPORTED_COMMODITIES:
            raise ValueError(
                f"{name} row {number} has unsupported commodity "
                f"{row['commodity']!r}"
            )
        if source_crops is not None:
            expected_crop = source_crops.get(row["commodity"])
            if expected_crop is None or row["source_crop"] != expected_crop:
                raise ValueError(
                    f"{name} row {number} has incompatible crop identity "
                    f"{row['source_crop']!r} for {row['commodity']!r}"
                )
        if canada_only and row["geography"] != CANADA:
            raise ValueError(
                f"{name} row {number} has incompatible geography "
                f"{row['geography']!r}; expected {CANADA!r}"
            )
        if july_only and row["snapshot_period"] != "July":
            raise ValueError(
                f"{name} row {number} is not a July completed-crop-year row"
            )
        key = tuple(row[field] for field in key_fields)
        if key in keys:
            raise ValueError(f"Duplicate {name} observation for {key!r}")
        keys.add(key)


def _validate_artifact_identities(loaded: Mapping[str, Sequence[Mapping[str, str]]]) -> None:
    production_units = {
        "production": "tonnes",
        "seeded-area": "hectares",
        "harvested-area": "hectares",
        "yield": "tonnes per hectare",
    }
    for number, row in enumerate(loaded["production"], start=2):
        expected_unit = production_units.get(row["metric"])
        if row["geography"] not in GEOGRAPHIES or expected_unit != row["unit"]:
            raise ValueError(f"production row {number} has an incompatible identity")

    stock_periods = {
        "03": ("March 31", "03-31"),
        "07": ("July 31", "07-31"),
        "12": ("December 31", "12-31"),
    }
    for number, row in enumerate(loaded["stocks"], start=2):
        try:
            year, month = row["reference_period"].split("-")
            snapshot, suffix = stock_periods[month]
        except (KeyError, ValueError) as exc:
            raise ValueError(
                f"stocks row {number} has an incompatible reporting period"
            ) from exc
        if (
            row["geography"] not in GEOGRAPHIES
            or row["normalized_unit"] != "tonnes"
            or row["stock_type"]
            not in {
                "Farm and commercial, total",
                "Farm stocks",
                "Commercial stocks",
            }
            or row["snapshot_period"] != snapshot
            or row["reference_date"] != f"{year}-{suffix}"
        ):
            raise ValueError(f"stocks row {number} has an incompatible identity")

    supply_periods = {"03": "March", "07": "July", "12": "December"}
    for name in ("supply_disposition", "stocks_to_use"):
        for number, row in enumerate(loaded[name], start=2):
            try:
                year_text, month = row["reference_period"].split("-")
                year = int(year_text)
                snapshot = supply_periods[month]
                crop_start, crop_end = (int(value) for value in row["crop_year"].split("/"))
            except (KeyError, ValueError) as exc:
                raise ValueError(
                    f"{name} row {number} has an incompatible reporting period"
                ) from exc
            expected_start = year if month == "12" else year - 1
            if (
                row["snapshot_period"] != snapshot
                or crop_start != expected_start
                or crop_end != expected_start + 1
            ):
                raise ValueError(
                    f"{name} row {number} has an incompatible reporting period"
                )
            if name == "supply_disposition" and row["normalized_unit"] != "tonnes":
                raise ValueError(
                    f"supply_disposition row {number} has an incompatible unit"
                )
            if name == "supply_disposition" and row["measure"] not in MEASURES:
                raise ValueError(
                    f"supply_disposition row {number} has an incompatible measure"
                )
            if name == "stocks_to_use":
                calculated = row["calculation_status"] == "calculated"
                if row["formula"] != FORMULA or row["calculation_status"] not in {
                    "calculated",
                    "unavailable",
                }:
                    raise ValueError(
                        f"stocks_to_use row {number} has an incompatible method"
                    )
                if calculated != bool(row["stocks_to_use_pct"].strip()):
                    raise ValueError(
                        f"stocks_to_use row {number} has an incompatible "
                        "calculation status"
                    )


def _choose(requested: str | None, options: tuple[str, ...], preferred: str) -> str | None:
    if requested is not None:
        if requested not in options:
            raise ValueError(f"Selected identity {requested!r} is not available")
        return requested
    if preferred in options:
        return preferred
    return options[0] if options else None


def _observation(
    row: Mapping[str, str],
    *,
    label: str,
    value_field: str,
    unit: str,
    observation_kind: str,
    source_label: str,
    crop_year: str = "",
    release_field: str = "release_date",
    retrieval_field: str = "retrieved_at",
) -> DisplayObservation:
    return DisplayObservation(
        label=label,
        value=_decimal(row[value_field], f"{label} {row['reference_period']}"),
        unit=unit,
        reference_period=row["reference_period"],
        crop_year=crop_year,
        geography=row["geography"],
        source_table=row["source_table"],
        source_url=row["source_url"],
        release_date=row[release_field],
        retrieved_at=row[retrieval_field],
        publisher=row["publisher"],
        observation_kind=observation_kind,
        source_label=source_label,
        provenance=dict(row),
    )


def _unavailable(identity: str, detail: str = "series is absent") -> SeriesView:
    return SeriesView(False, f"{UNAVAILABLE}: {detail}", identity)


def _latest_row(rows: Sequence[Mapping[str, str]], period_field: str) -> Mapping[str, str]:
    # Sorting the full identity, rather than input order, makes selection stable.
    return max(rows, key=lambda row: (row[period_field], tuple(sorted(row.items()))))


def build_overview(
    paths: ArtifactPaths,
    commodity: str,
    geography: str = CANADA,
    *,
    stock_type: str | None = None,
    stock_snapshot: str | None = None,
    supply_measure: str | None = None,
    supply_snapshot: str | None = None,
) -> UnifiedOverview:
    """Load and strictly select one unified official commodity overview."""
    if commodity not in SUPPORTED_COMMODITIES:
        raise ValueError(f"Unsupported commodity {commodity!r}")

    errors: dict[str, str] = {}
    loaded: dict[str, list[dict[str, str]]] = {}
    specs = (
        ("production", paths.production, PRODUCTION_FIELDS),
        ("stocks", paths.stocks, STOCK_FIELDS),
        ("supply_disposition", paths.supply_disposition, SUPPLY_FIELDS),
        ("stocks_to_use", paths.stocks_to_use, RATIO_FIELDS),
    )
    for name, path, fields in specs:
        try:
            loaded[name] = _read(path, fields, name)
        except FileNotFoundError as exc:
            loaded[name] = []
            errors[name] = str(exc)

    production_source_crops = {
        slug: definition.statcan_name for slug, definition in COMMODITIES.items()
    }
    validators = (
        ("production", PRODUCTION_TABLE, ("reference_period", "commodity", "geography", "metric"), False, False, production_source_crops),
        ("stocks", STOCKS_TABLE, ("reference_period", "commodity", "geography", "stock_type"), False, False, STOCK_SOURCE_CROPS),
        ("supply_disposition", SUPPLY_TABLE, ("reference_period", "commodity", "measure"), True, False, SUPPLY_SOURCE_CROPS),
        ("stocks_to_use", SUPPLY_TABLE, ("reference_period", "commodity"), True, True, SUPPLY_SOURCE_CROPS),
    )
    for name, table, keys, canada_only, july_only, source_crops in validators:
        _validate_rows(
            loaded[name], name=name, table=table, key_fields=keys,
            canada_only=canada_only, july_only=july_only,
            source_crops=source_crops,
        )
    _validate_artifact_identities(loaded)

    production_rows = loaded["production"]
    geographies = GEOGRAPHIES
    if geography not in geographies:
        raise ValueError(f"Selected geography {geography!r} is not available")

    production: dict[str, SeriesView] = {}
    for metric, label in (
        ("production", "Production"),
        ("seeded-area", "Seeded area"),
        ("harvested-area", "Harvested area"),
        ("yield", "Yield"),
    ):
        matches = [
            row for row in production_rows
            if row["commodity"] == commodity
            and row["geography"] == geography
            and row["metric"] == metric
        ]
        identity = f"{label} · {geography}"
        if not matches:
            production[metric] = _unavailable(identity)
            continue
        observations = tuple(
            _observation(
                row, label=label, value_field="value", unit=row["unit"],
                observation_kind="Official published observation",
                source_label=row["source_crop"],
            )
            for row in sorted(matches, key=lambda item: item["reference_period"])
        )
        latest = observations[-1]
        production[metric] = SeriesView(
            latest.value is not None,
            "" if latest.value is not None else f"{UNAVAILABLE}: latest source row is unpublished",
            identity, observations, latest,
        )

    commodity_stocks = [
        row for row in loaded["stocks"]
        if row["commodity"] == commodity and row["geography"] == geography
    ]
    stock_types = tuple(dict.fromkeys(
        item for item in ("Farm and commercial, total", "Farm stocks", "Commercial stocks")
        if any(row["stock_type"] == item for row in commodity_stocks)
    ))
    selected_stock_type = _choose(
        stock_type, stock_types,
        "Farm and commercial, total" if geography == CANADA else "Farm stocks",
    )
    stock_type_rows = [row for row in commodity_stocks if row["stock_type"] == selected_stock_type]
    stock_snapshots = tuple(
        item for item in ("March 31", "July 31", "December 31")
        if any(row["snapshot_period"] == item for row in stock_type_rows)
    )
    if stock_snapshot is None and stock_type_rows:
        newest = _latest_row(stock_type_rows, "reference_date")
        selected_stock_snapshot = newest["snapshot_period"]
    else:
        selected_stock_snapshot = _choose(stock_snapshot, stock_snapshots, "July 31")
    stock_matches = [
        row for row in stock_type_rows
        if row["snapshot_period"] == selected_stock_snapshot
    ]
    stock_identity = f"{selected_stock_type or 'Stocks'} · {selected_stock_snapshot or 'snapshot'} · {geography}"
    if not stock_matches:
        stocks = _unavailable(stock_identity)
    else:
        stock_observations = tuple(
            _observation(
                row, label=row["stock_type"], value_field="normalized_tonnes",
                unit=row["normalized_unit"],
                observation_kind="Official published observation",
                source_label=f"{row['source_crop']} · {row['stock_type']}",
            )
            for row in sorted(stock_matches, key=lambda item: item["reference_date"])
        )
        latest_stock = stock_observations[-1]
        comparison = None
        reason = ""
        if latest_stock.value is None:
            reason = f"{UNAVAILABLE}: latest source row is unpublished"
        else:
            comparison = compare_same_snapshot(
                {item.reference_period: item.value for item in stock_observations}
            )
            if comparison.reference_period != latest_stock.reference_period:
                raise ValueError("Stocks comparison selected an older observation")
        stocks = SeriesView(
            latest_stock.value is not None, reason, stock_identity,
            stock_observations, latest_stock, comparison,
        )

    commodity_supply = [
        row for row in loaded["supply_disposition"] if row["commodity"] == commodity
    ]
    supply_measures = tuple(
        measure for measure in MEASURES
        if any(row["measure"] == measure for row in commodity_supply)
    )
    selected_supply_measure = _choose(supply_measure, supply_measures, "Total ending stocks")
    measure_rows = [row for row in commodity_supply if row["measure"] == selected_supply_measure]
    supply_snapshots = tuple(
        item for item in ("March", "July", "December")
        if any(row["snapshot_period"] == item for row in measure_rows)
    )
    selected_supply_snapshot = _choose(supply_snapshot, supply_snapshots, "July")
    supply_matches = [
        row for row in measure_rows if row["snapshot_period"] == selected_supply_snapshot
    ]
    supply_identity = f"{selected_supply_measure or 'Measure'} · {selected_supply_snapshot or 'snapshot'} · Canada"
    if not supply_matches:
        supply = _unavailable(supply_identity)
    else:
        supply_observations = tuple(
            _observation(
                row, label=row["measure"], value_field="normalized_tonnes",
                unit=row["normalized_unit"], crop_year=row["crop_year"],
                observation_kind="Official published observation",
                source_label=f"{row['source_crop']} · {row['measure']}",
            )
            for row in sorted(supply_matches, key=lambda item: item["reference_period"])
        )
        latest_supply = supply_observations[-1]
        comparison = None
        reason = ""
        if latest_supply.value is None:
            reason = f"{UNAVAILABLE}: latest source row is unpublished"
        else:
            comparison = compare_same_snapshot(
                {item.reference_period: item.value for item in supply_observations}
            )
            if comparison.reference_period != latest_supply.reference_period:
                raise ValueError("Supply comparison selected an older observation")
        supply = SeriesView(
            latest_supply.value is not None, reason, supply_identity,
            supply_observations, latest_supply, comparison,
        )

    ratio_matches = [
        row for row in loaded["stocks_to_use"] if row["commodity"] == commodity
    ]
    if not ratio_matches:
        ratio = _unavailable("July completed crop years · Canada")
    else:
        ratio_observations = tuple(
            _observation(
                row, label="Stocks-to-use", value_field="stocks_to_use_pct",
                unit="percent", crop_year=row["crop_year"],
                release_field="source_release_date",
                retrieval_field="source_retrieval_date",
                observation_kind="Derived official calculation",
                source_label=f"{row['source_crop']} · {row['formula']}",
            )
            for row in sorted(ratio_matches, key=lambda item: item["reference_period"])
        )
        latest_ratio = ratio_observations[-1]
        latest_ratio_row = _latest_row(ratio_matches, "reference_period")
        calculated = latest_ratio_row["calculation_status"] == "calculated" and latest_ratio.value is not None
        reason = "" if calculated else (
            f"{UNAVAILABLE}: "
            + (latest_ratio_row["calculation_reason"] or "required inputs are unavailable")
        )
        ratio = SeriesView(
            calculated, reason, "July completed crop years · Canada",
            ratio_observations, latest_ratio,
        )

    snapshot = tuple(
        item
        for item in (
            production["production"].latest,
            production["seeded-area"].latest,
            production["harvested-area"].latest,
            production["yield"].latest,
            stocks.latest,
        )
        if item is not None
    )
    if ratio.latest is not None:
        ratio_row = ratio.latest.provenance
        snapshot += (
            _observation(
                ratio_row, label="Ending stocks", value_field="ending_stocks_tonnes",
                unit="tonnes", crop_year=ratio_row["crop_year"],
                release_field="source_release_date", retrieval_field="source_retrieval_date",
                observation_kind="Official input to derived calculation",
                source_label=f"{ratio_row['source_crop']} · Total ending stocks",
            ),
            _observation(
                ratio_row, label="Total use", value_field="total_use_tonnes",
                unit="tonnes", crop_year=ratio_row["crop_year"],
                release_field="source_release_date", retrieval_field="source_retrieval_date",
                observation_kind="Derived official calculation",
                source_label="Total exports + Total domestic disappearance",
            ),
            ratio.latest,
        )

    return UnifiedOverview(
        commodity=commodity, geography=geography, geography_options=geographies,
        stock_type=selected_stock_type, stock_type_options=stock_types,
        stock_snapshot=selected_stock_snapshot, stock_snapshot_options=stock_snapshots,
        supply_measure=selected_supply_measure, supply_measure_options=supply_measures,
        supply_snapshot=selected_supply_snapshot, supply_snapshot_options=supply_snapshots,
        snapshot=snapshot, production=production, stocks=stocks,
        supply_disposition=supply, stocks_to_use=ratio, artifact_errors=errors,
    )
