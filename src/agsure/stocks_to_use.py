from __future__ import annotations

import argparse
import csv
import tempfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence


SOURCE_TABLE = "32-10-0013-01"
PRODUCT_ID = "32100013"
GEOGRAPHY = "Canada"
SNAPSHOT_PERIOD = "July"
COMMODITIES = ("barley", "canola", "durum-wheat", "dry-peas")
ENDING_STOCKS = "Total ending stocks"
TOTAL_EXPORTS = "Total exports"
DOMESTIC_DISAPPEARANCE = "Total domestic disappearance"
TOTAL_DISPOSITION = "Total disposition"
REQUIRED_MEASURES = (ENDING_STOCKS, TOTAL_EXPORTS, DOMESTIC_DISAPPEARANCE)
RECONCILIATION_TOLERANCE_TONNES = Decimal("200")
METHODOLOGY_VERSION = "0.5.0"
FORMULA = (
    "Total ending stocks / (Total exports + Total domestic disappearance) * 100"
)
DEFAULT_INPUT = Path("data/processed/statcan_supply_disposition.csv")
DEFAULT_OUTPUT = Path("data/processed/statcan_stocks_to_use.csv")

REQUIRED_SOURCE_FIELDS = {
    "publisher",
    "source_table",
    "product_id",
    "source_url",
    "table_url",
    "release_date",
    "retrieved_at",
    "reference_period",
    "snapshot_period",
    "crop_year",
    "reporting_period_start",
    "reporting_period_end",
    "reporting_period_basis",
    "commodity",
    "source_crop",
    "geography",
    "dguid",
    "source_note_ids",
    "measure",
    "original_value",
    "original_unit",
    "uom_id",
    "scalar_factor",
    "scalar_id",
    "normalized_tonnes",
    "normalized_unit",
    "observation_status",
    "status_marker",
    "revision_marker",
    "symbol",
    "terminated",
    "decimals",
    "vector",
    "coordinate",
}

PROVENANCE_FIELDS = (
    "measure",
    "original_value",
    "original_unit",
    "uom_id",
    "scalar_factor",
    "scalar_id",
    "normalized_tonnes",
    "normalized_unit",
    "observation_status",
    "status_marker",
    "revision_marker",
    "symbol",
    "terminated",
    "decimals",
    "vector",
    "coordinate",
)
PROVENANCE_PREFIXES = {
    ENDING_STOCKS: "ending_stocks_source",
    TOTAL_EXPORTS: "total_exports_source",
    DOMESTIC_DISAPPEARANCE: "domestic_disappearance_source",
    TOTAL_DISPOSITION: "total_disposition_source",
}
UNUSABLE_OBSERVATION_STATUSES = {
    "unavailable",
    "not applicable",
    "too unreliable to publish",
    "confidential",
    "below limit of detection",
    "missing",
}
UNUSABLE_STATUS_MARKERS = {"..", "...", "F", "x", "<LOD"}

OUTPUT_FIELDS = (
    "publisher",
    "source_table",
    "product_id",
    "source_url",
    "table_url",
    "source_release_date",
    "source_retrieval_date",
    "source_vintage_basis",
    "reference_period",
    "snapshot_period",
    "crop_year",
    "reporting_period_start",
    "reporting_period_end",
    "reporting_period_basis",
    "commodity",
    "source_crop",
    "geography",
    "dguid",
    "source_note_ids",
    "ending_stocks_tonnes",
    "total_exports_tonnes",
    "total_domestic_disappearance_tonnes",
    "total_use_tonnes",
    "stocks_to_use_pct",
    "total_disposition_tonnes",
    "reconciliation_sum_tonnes",
    "reconciliation_difference_tonnes",
    "reconciliation_tolerance_tonnes",
    "reconciliation_status",
    "calculation_status",
    "calculation_reason",
    "formula",
    "methodology_version",
) + tuple(
    f"{prefix}_{field}"
    for prefix in PROVENANCE_PREFIXES.values()
    for field in PROVENANCE_FIELDS
)


def _format_decimal(value: Decimal | None) -> str:
    if value is None:
        return ""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _source_value(row: Mapping[str, str] | None, label: str) -> tuple[Decimal | None, str]:
    if row is None:
        return None, f"required input absent: {label}"
    status = row.get("observation_status", "").strip()
    marker = row.get("status_marker", "").strip()
    value = row.get("normalized_tonnes", "").strip()
    if status in UNUSABLE_OBSERVATION_STATUSES or marker in UNUSABLE_STATUS_MARKERS:
        detail = status or f"source status {marker}"
        return None, f"{label} is unavailable ({detail})"
    if not value:
        detail = status or (f"source status {marker}" if marker else "missing")
        return None, f"{label} is unavailable ({detail})"
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return None, f"{label} is nonnumeric ({value!r})"
    if not parsed.is_finite():
        return None, f"{label} is nonnumeric ({value!r})"
    return parsed, ""


def _copy_provenance(
    output: dict[str, str], measure: str, row: Mapping[str, str] | None
) -> None:
    prefix = PROVENANCE_PREFIXES[measure]
    for field in PROVENANCE_FIELDS:
        output[f"{prefix}_{field}"] = "" if row is None else row.get(field, "")


def _validate_identity(
    row: Mapping[str, str], commodity: str, crop_year: str, reference_period: str
) -> str:
    expected = {
        "source_table": SOURCE_TABLE,
        "product_id": PRODUCT_ID,
        "geography": GEOGRAPHY,
        "snapshot_period": SNAPSHOT_PERIOD,
        "commodity": commodity,
        "crop_year": crop_year,
        "reference_period": reference_period,
        "normalized_unit": "tonnes",
    }
    mismatches = [
        f"{field}={row.get(field, '')!r} (expected {value!r})"
        for field, value in expected.items()
        if row.get(field, "") != value
    ]
    return "; ".join(mismatches)


def _validate_completed_period(row: Mapping[str, str]) -> str:
    reference_period = row.get("reference_period", "")
    crop_year = row.get("crop_year", "")
    try:
        end_text, month = reference_period.split("-")
        start_text, crop_end_text = crop_year.split("/")
        end = int(end_text)
        start = int(start_text)
        crop_end = int(crop_end_text)
    except ValueError:
        return "invalid July reference period or crop-year format"
    if month != "07" or start != end - 1 or crop_end != end:
        return "reference period is not the July completion of the stated crop year"
    if row.get("reporting_period_start", "") != f"{start:04d}-08":
        return "reporting period does not start in August of the stated crop year"
    if row.get("reporting_period_end", "") != reference_period:
        return "reporting period end does not match the July reference period"
    return ""


def calculate_rows(rows: Iterable[Mapping[str, str]]) -> Iterator[dict[str, str]]:
    """Calculate completed-crop-year ratios from exact July source rows."""
    groups: dict[tuple[str, str, str], dict[str, Mapping[str, str]]] = {}
    representatives: dict[tuple[str, str, str], Mapping[str, str]] = {}
    for row_number, row in enumerate(rows, start=2):
        if (
            row.get("source_table") != SOURCE_TABLE
            or row.get("product_id") != PRODUCT_ID
            or row.get("geography") != GEOGRAPHY
            or row.get("snapshot_period") != SNAPSHOT_PERIOD
            or row.get("commodity") not in COMMODITIES
        ):
            continue
        key = (
            row.get("commodity", ""),
            row.get("crop_year", ""),
            row.get("reference_period", ""),
        )
        group = groups.setdefault(key, {})
        representatives.setdefault(key, row)
        measure = row.get("measure", "")
        if measure not in (*REQUIRED_MEASURES, TOTAL_DISPOSITION):
            continue
        if measure in group:
            raise ValueError(
                f"Duplicate source observation for {key!r}, {measure!r} "
                f"at input row {row_number}"
            )
        group[measure] = row

    for (commodity, crop_year, reference_period), source_rows in sorted(
        groups.items()
    ):
        representative = representatives[(commodity, crop_year, reference_period)]
        output = {field: "" for field in OUTPUT_FIELDS}
        output.update(
            {
                "publisher": representative.get("publisher", ""),
                "source_table": representative.get("source_table", ""),
                "product_id": representative.get("product_id", ""),
                "source_url": representative.get("source_url", ""),
                "table_url": representative.get("table_url", ""),
                "source_release_date": representative.get("release_date", ""),
                "source_retrieval_date": representative.get("retrieved_at", ""),
                "source_vintage_basis": "Latest revised cube vintage at retrieval",
                "reference_period": reference_period,
                "snapshot_period": SNAPSHOT_PERIOD,
                "crop_year": crop_year,
                "reporting_period_start": representative.get(
                    "reporting_period_start", ""
                ),
                "reporting_period_end": representative.get("reporting_period_end", ""),
                "reporting_period_basis": representative.get(
                    "reporting_period_basis", ""
                ),
                "commodity": commodity,
                "source_crop": representative.get("source_crop", ""),
                "geography": representative.get("geography", ""),
                "dguid": representative.get("dguid", ""),
                "source_note_ids": representative.get("source_note_ids", ""),
                "reconciliation_tolerance_tonnes": _format_decimal(
                    RECONCILIATION_TOLERANCE_TONNES
                ),
                "formula": FORMULA,
                "methodology_version": METHODOLOGY_VERSION,
                "calculation_status": "unavailable",
                "reconciliation_status": "not_available",
            }
        )
        for measure in (*REQUIRED_MEASURES, TOTAL_DISPOSITION):
            _copy_provenance(output, measure, source_rows.get(measure))

        reasons: list[str] = []
        period_error = _validate_completed_period(representative)
        if period_error:
            reasons.append(period_error)
        shared_fields = (
            "publisher",
            "source_url",
            "table_url",
            "release_date",
            "retrieved_at",
            "reporting_period_start",
            "reporting_period_end",
            "reporting_period_basis",
            "source_crop",
            "dguid",
        )
        for measure in REQUIRED_MEASURES:
            row = source_rows.get(measure)
            if row is None:
                continue
            identity_error = _validate_identity(
                row, commodity, crop_year, reference_period
            )
            if identity_error:
                reasons.append(f"{measure} identity mismatch: {identity_error}")
            measure_period_error = _validate_completed_period(row)
            if measure_period_error:
                reasons.append(f"{measure}: {measure_period_error}")
            for field in shared_fields:
                if row.get(field, "") != representative.get(field, ""):
                    reasons.append(f"{measure} does not match source {field}")

        values: dict[str, Decimal | None] = {}
        for measure in REQUIRED_MEASURES:
            values[measure], reason = _source_value(source_rows.get(measure), measure)
            if reason:
                reasons.append(reason)

        output["ending_stocks_tonnes"] = _format_decimal(values[ENDING_STOCKS])
        output["total_exports_tonnes"] = _format_decimal(values[TOTAL_EXPORTS])
        output["total_domestic_disappearance_tonnes"] = _format_decimal(
            values[DOMESTIC_DISAPPEARANCE]
        )
        if reasons:
            output["calculation_reason"] = "; ".join(dict.fromkeys(reasons))
            yield output
            continue

        ending = values[ENDING_STOCKS]
        exports = values[TOTAL_EXPORTS]
        domestic = values[DOMESTIC_DISAPPEARANCE]
        assert ending is not None and exports is not None and domestic is not None
        total_use = exports + domestic
        output["total_use_tonnes"] = _format_decimal(total_use)
        if total_use <= 0:
            output["calculation_reason"] = (
                f"total use denominator must be positive; calculated {total_use} tonnes"
            )
            yield output
            continue

        output["stocks_to_use_pct"] = _format_decimal(ending / total_use * 100)
        output["calculation_status"] = "calculated"
        output["calculation_reason"] = ""

        disposition_row = source_rows.get(TOTAL_DISPOSITION)
        if disposition_row is not None:
            disposition_identity_error = _validate_identity(
                disposition_row, commodity, crop_year, reference_period
            )
            disposition_shared_errors = [
                field
                for field in shared_fields
                if disposition_row.get(field, "") != representative.get(field, "")
            ]
            if disposition_identity_error or disposition_shared_errors:
                output["reconciliation_status"] = "not_available"
                yield output
                continue
        disposition, disposition_reason = _source_value(
            disposition_row, TOTAL_DISPOSITION
        )
        if disposition_reason:
            output["reconciliation_status"] = "not_available"
            yield output
            continue
        assert disposition is not None
        reconciliation_sum = total_use + ending
        difference = reconciliation_sum - disposition
        output["total_disposition_tonnes"] = _format_decimal(disposition)
        output["reconciliation_sum_tonnes"] = _format_decimal(reconciliation_sum)
        output["reconciliation_difference_tonnes"] = _format_decimal(difference)
        output["reconciliation_status"] = (
            "reconciled"
            if abs(difference) <= RECONCILIATION_TOLERANCE_TONNES
            else "unreconciled"
        )
        yield output


def rebuild(input_path: str | Path, output_path: str | Path) -> int:
    """Atomically rebuild the local stocks-to-use CSV from normalized rows."""
    source = Path(input_path)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with source.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            missing = REQUIRED_SOURCE_FIELDS - set(reader.fieldnames or [])
            if missing:
                raise ValueError(
                    "Missing required normalized columns: "
                    + ", ".join(sorted(missing))
                )
            calculated = list(calculate_rows(reader))
        if not calculated:
            raise ValueError("No completed July crop years matched the configured slice")
        keys = [(row["commodity"], row["crop_year"]) for row in calculated]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate commodity and crop-year keys in derived output")
        with tempfile.NamedTemporaryFile(
            "w",
            dir=destination.parent,
            encoding="utf-8",
            newline="",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
            writer.writeheader()
            writer.writerows(calculated)
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return len(calculated)


@dataclass(frozen=True)
class HistorySummary:
    latest_crop_year: str
    latest_ratio: Decimal
    previous_ratio: Decimal | None
    previous_change_percentage_points: Decimal | None
    five_year_average_ratio: Decimal | None
    five_year_deviation_percentage_points: Decimal | None


def summarize_history(rows: Sequence[Mapping[str, str]]) -> HistorySummary:
    """Summarize strict consecutive calculated crop years for the dashboard."""
    valid: dict[int, tuple[str, Decimal]] = {}
    for row in rows:
        if row.get("calculation_status") != "calculated":
            continue
        try:
            start_text, end_text = row.get("crop_year", "").split("/")
            start = int(start_text)
            end = int(end_text)
            ratio = Decimal(row.get("stocks_to_use_pct", ""))
        except (ValueError, InvalidOperation):
            continue
        if end != start + 1 or not ratio.is_finite():
            continue
        if start in valid:
            raise ValueError(f"Duplicate calculated crop year {row['crop_year']!r}")
        valid[start] = (row["crop_year"], ratio)
    if not valid:
        raise ValueError("No calculated stocks-to-use ratios are available")
    latest_start = max(valid)
    latest_year, latest_ratio = valid[latest_start]
    previous = valid.get(latest_start - 1)
    previous_ratio = None if previous is None else previous[1]
    previous_change = (
        None if previous_ratio is None else latest_ratio - previous_ratio
    )
    prior = [valid.get(year) for year in range(latest_start - 5, latest_start)]
    if any(item is None for item in prior):
        average = None
        deviation = None
    else:
        ratios = [item[1] for item in prior if item is not None]
        average = sum(ratios, Decimal("0")) / Decimal(5)
        deviation = latest_ratio - average
    return HistorySummary(
        latest_crop_year=latest_year,
        latest_ratio=latest_ratio,
        previous_ratio=previous_ratio,
        previous_change_percentage_points=previous_change,
        five_year_average_ratio=average,
        five_year_deviation_percentage_points=deviation,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild completed-crop-year official stocks-to-use ratios from the "
            "normalized Statistics Canada supply-and-disposition CSV."
        )
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    count = rebuild(args.input, args.output)
    print(f"Wrote {count:,} completed crop-year rows to {args.output}")
    print(f"Formula: {FORMULA}")
    print(
        "Reconciliation tolerance: "
        f"{_format_decimal(RECONCILIATION_TOLERANCE_TONNES)} tonnes"
    )


if __name__ == "__main__":
    main()
