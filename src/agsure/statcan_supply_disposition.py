from __future__ import annotations

import argparse
import csv
import io
import tempfile
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Iterator, Mapping

from agsure.statcan import (
    DownloadMetadata,
    _data_member,
    _format_decimal,
    _scalar_multiplier,
    download_archive,
)


PUBLISHER = "Statistics Canada"
SOURCE_TABLE = "32-10-0013-01"
PRODUCT_ID = "32100013"
SOURCE_URL = "https://www150.statcan.gc.ca/n1/tbl/csv/32100013-eng.zip"
DOWNLOAD_URL = SOURCE_URL
TABLE_URL = "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3210001301"
DEFAULT_CACHE_DIR = Path("data/raw/statcan")
DEFAULT_OUTPUT = Path("data/processed/statcan_supply_disposition.csv")

GEOGRAPHY = "Canada"
CROP_SLUGS = {
    "Barley": "barley",
    "Canola": "canola",
    "Durum wheat": "durum-wheat",
    "Dry peas": "dry-peas",
}
# Note IDs point into the metadata CSV retained inside every cached raw ZIP.
# IDs 1, 2, and 23 are relevant cube notes; the remainder are crop-member notes.
CROP_SOURCE_NOTE_IDS = {
    "Barley": "1;2;5;9;12;23;24;25;26",
    "Canola": "1;2;5;9;12;16;18;21;23;24;25",
    "Durum wheat": "1;2;5;6;12;13;14;23;24;25;26",
    "Dry peas": "1;2;8;23",
}
MEASURES = (
    "Total supplies",
    "Total beginning stocks",
    "Beginning stocks on farms",
    "Beginning stocks in commercial positions",
    "Production",
    "Imports",
    "Total disposition",
    "Total exports",
    "Grain exports",
    "Product exports",
    "Total domestic disappearance",
    "Human food",
    "Seed requirements",
    "Industrial use",
    "Loss in handling",
    "Animal feed, waste and dockage",
    "Other domestic disappearance",
    "Total ending stocks",
    "Ending stocks on farms",
    "Ending stocks in commercial positions",
)
UNPUBLISHED_STATUSES = {"..", "...", "F", "x", "<LOD"}
STATUS_LABELS = {
    "..": "unavailable",
    "...": "not applicable",
    "F": "too unreliable to publish",
    "x": "confidential",
    "<LOD": "below limit of detection",
}
SNAPSHOT_PERIODS = {"03": "March", "07": "July", "12": "December"}

OUTPUT_FIELDS = (
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
)

REQUIRED_SOURCE_FIELDS = {
    "REF_DATE",
    "GEO",
    "DGUID",
    "Type of crop",
    "Supply and disposition of grains",
    "UOM",
    "UOM_ID",
    "SCALAR_FACTOR",
    "SCALAR_ID",
    "VECTOR",
    "COORDINATE",
    "VALUE",
    "STATUS",
    "SYMBOL",
    "TERMINATED",
    "DECIMALS",
}


def download_table(
    cache_dir: str | Path = DEFAULT_CACHE_DIR, *, force: bool = False
) -> tuple[Path, DownloadMetadata]:
    """Download and cache the official supply-and-disposition table."""
    return download_archive(
        cache_dir,
        publisher=PUBLISHER,
        source_table=SOURCE_TABLE,
        product_id=PRODUCT_ID,
        source_url=SOURCE_URL,
        download_url=DOWNLOAD_URL,
        table_url=TABLE_URL,
        force=force,
    )


def _period_fields(reference_period: str) -> tuple[str, str, str, str]:
    try:
        year_text, month = reference_period.split("-")
        year = int(year_text)
        snapshot = SNAPSHOT_PERIODS[month]
        if len(year_text) != 4:
            raise ValueError
    except (KeyError, ValueError) as exc:
        raise ValueError(
            f"Unsupported Statistics Canada reference period {reference_period!r}"
        ) from exc

    crop_year_start = year if month == "12" else year - 1
    crop_year = f"{crop_year_start}/{crop_year_start + 1}"
    reporting_start = f"{crop_year_start:04d}-08"
    reporting_end = reference_period
    return snapshot, crop_year, reporting_start, reporting_end


def _observation_status(status_marker: str, value: str) -> str:
    if status_marker in STATUS_LABELS:
        return STATUS_LABELS[status_marker]
    if not value:
        return "missing"
    return "official"


def normalize_rows(
    rows: Iterable[Mapping[str, str]], metadata: DownloadMetadata
) -> Iterator[dict[str, str]]:
    """Normalize exact source members without combining crops or measures."""
    for row_number, row in enumerate(rows, start=2):
        geography = row.get("GEO", "").strip()
        source_crop = row.get("Type of crop", "").strip()
        measure = row.get("Supply and disposition of grains", "").strip()
        if (
            geography != GEOGRAPHY
            or source_crop not in CROP_SLUGS
            or measure not in MEASURES
        ):
            continue

        original_unit = row.get("UOM", "").strip()
        if original_unit != "Metric tonnes":
            continue
        scalar_factor = row.get("SCALAR_FACTOR", "").strip()
        multiplier = _scalar_multiplier(scalar_factor)
        original_value = row.get("VALUE", "").strip()
        status_marker = row.get("STATUS", "").strip()
        normalized_tonnes = ""
        if original_value and status_marker not in UNPUBLISHED_STATUSES:
            try:
                normalized_tonnes = _format_decimal(
                    Decimal(original_value) * multiplier
                )
            except InvalidOperation as exc:
                raise ValueError(
                    f"Invalid VALUE {original_value!r} at source row {row_number}"
                ) from exc

        reference_period = row.get("REF_DATE", "").strip()
        snapshot, crop_year, reporting_start, reporting_end = _period_fields(
            reference_period
        )
        symbol = row.get("SYMBOL", "").strip()
        revision_marker = "r" if "r" in {status_marker, symbol} else ""
        yield {
            "publisher": metadata.publisher,
            "source_table": metadata.source_table,
            "product_id": metadata.product_id,
            "source_url": metadata.source_url,
            "table_url": TABLE_URL,
            "release_date": metadata.release_date,
            "retrieved_at": metadata.retrieved_at,
            "reference_period": reference_period,
            "snapshot_period": snapshot,
            "crop_year": crop_year,
            "reporting_period_start": reporting_start,
            "reporting_period_end": reporting_end,
            "reporting_period_basis": "Cumulative over the crop year",
            "commodity": CROP_SLUGS[source_crop],
            "source_crop": source_crop,
            "geography": geography,
            "dguid": row.get("DGUID", "").strip(),
            "source_note_ids": CROP_SOURCE_NOTE_IDS[source_crop],
            "measure": measure,
            "original_value": original_value,
            "original_unit": original_unit,
            "uom_id": row.get("UOM_ID", "").strip(),
            "scalar_factor": scalar_factor,
            "scalar_id": row.get("SCALAR_ID", "").strip(),
            "normalized_tonnes": normalized_tonnes,
            "normalized_unit": "tonnes",
            "observation_status": _observation_status(
                status_marker, original_value
            ),
            "status_marker": status_marker,
            "revision_marker": revision_marker,
            "symbol": symbol,
            "terminated": row.get("TERMINATED", "").strip(),
            "decimals": row.get("DECIMALS", "").strip(),
            "vector": row.get("VECTOR", "").strip(),
            "coordinate": row.get("COORDINATE", "").strip(),
        }


def process_archive(
    archive: str | Path, output: str | Path, metadata: DownloadMetadata
) -> int:
    """Write the configured supply-and-disposition slice from a local ZIP."""
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_output: Path | None = None
    try:
        with zipfile.ZipFile(archive) as bundle:
            member = _data_member(bundle)
            with bundle.open(member) as raw_handle:
                with io.TextIOWrapper(
                    raw_handle, encoding="utf-8-sig", newline=""
                ) as handle:
                    reader = csv.DictReader(handle)
                    missing = REQUIRED_SOURCE_FIELDS - set(reader.fieldnames or [])
                    if missing:
                        raise ValueError(
                            "Missing required StatCan columns: "
                            + ", ".join(sorted(missing))
                        )
                    with tempfile.NamedTemporaryFile(
                        "w",
                        dir=output_path.parent,
                        encoding="utf-8",
                        newline="",
                        delete=False,
                    ) as temp:
                        temporary_output = Path(temp.name)
                        writer = csv.DictWriter(temp, fieldnames=OUTPUT_FIELDS)
                        writer.writeheader()
                        count = 0
                        keys: set[tuple[str, str, str]] = set()
                        for row in normalize_rows(reader, metadata):
                            key = (
                                row["reference_period"],
                                row["commodity"],
                                row["measure"],
                            )
                            if key in keys:
                                raise ValueError(
                                    "Duplicate normalized observation for " + repr(key)
                                )
                            keys.add(key)
                            writer.writerow(row)
                            count += 1
        if count == 0:
            raise ValueError("No observations matched the configured StatCan slice")
        if temporary_output is None:
            raise RuntimeError("Processed output was not created")
        temporary_output.replace(output_path)
    finally:
        if temporary_output is not None:
            temporary_output.unlink(missing_ok=True)
    return count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download and normalize Statistics Canada table 32-10-0013-01."
    )
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--force", action="store_true", help="Replace the cached raw download"
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    archive, metadata = download_table(args.cache_dir, force=args.force)
    count = process_archive(archive, args.output, metadata)
    print(f"Wrote {count:,} normalized observations to {args.output}")
    print(f"Release date: {metadata.release_date}")
    print(f"Retrieved at: {metadata.retrieved_at}")
    print(f"Raw SHA-256: {metadata.sha256}")


if __name__ == "__main__":
    main()
