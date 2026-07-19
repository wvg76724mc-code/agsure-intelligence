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
SOURCE_TABLE = "32-10-0007-01"
PRODUCT_ID = "32100007"
SOURCE_URL = "https://www150.statcan.gc.ca/n1/tbl/csv/32100007-eng.zip"
DOWNLOAD_URL = SOURCE_URL
TABLE_URL = "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3210000701"
DEFAULT_CACHE_DIR = Path("data/raw/statcan")
DEFAULT_OUTPUT = Path("data/processed/statcan_crop_stocks.csv")

GEOGRAPHIES = {"Canada", "Alberta", "Saskatchewan", "Manitoba"}
CROP_SLUGS = {
    "Barley": "barley",
    "Canola (rapeseed)": "canola",
    "Wheat, durum": "durum-wheat",
    "Peas, dry": "dry-peas",
}
STOCK_TYPES = {
    "Farm and commercial, total",
    "Farm stocks",
    "Commercial stocks",
}
SNAPSHOT_PERIODS = {
    "03": ("March 31", "03-31"),
    "07": ("July 31", "07-31"),
    "12": ("December 31", "12-31"),
}
UNPUBLISHED_STATUSES = {"..", "...", "F", "x"}

OUTPUT_FIELDS = (
    "publisher",
    "source_table",
    "product_id",
    "source_url",
    "release_date",
    "retrieved_at",
    "reference_period",
    "reference_date",
    "snapshot_period",
    "commodity",
    "source_crop",
    "geography",
    "dguid",
    "stock_type",
    "original_value",
    "original_unit",
    "scalar_factor",
    "normalized_tonnes",
    "normalized_unit",
    "observation_status",
    "status_marker",
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
    "Type of stock",
    "Type of crop",
    "UOM",
    "SCALAR_FACTOR",
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
    """Download and cache the official crop-stocks table."""
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


def _snapshot_fields(reference_period: str) -> tuple[str, str]:
    try:
        year, month = reference_period.split("-")
        label, month_day = SNAPSHOT_PERIODS[month]
        if len(year) != 4 or not year.isdigit():
            raise ValueError
    except (KeyError, ValueError) as exc:
        raise ValueError(
            f"Unsupported Statistics Canada reference period {reference_period!r}"
        ) from exc
    return label, f"{year}-{month_day}"


def _observation_status(
    reference_period: str, geography: str, stock_type: str
) -> str:
    """Classify values whose published methodology is explicitly modelled."""
    year, month = reference_period.split("-")
    if stock_type != "Farm stocks":
        return "estimated"
    if month == "07" and int(year) >= 2025:
        return "modelled"
    if month == "03" and int(year) >= 2023 and geography != "Canada":
        return "modelled"
    return "estimated"


def normalize_rows(
    rows: Iterable[Mapping[str, str]], metadata: DownloadMetadata
) -> Iterator[dict[str, str]]:
    for row_number, row in enumerate(rows, start=2):
        geography = row.get("GEO", "").strip()
        source_crop = row.get("Type of crop", "").strip()
        stock_type = row.get("Type of stock", "").strip()
        if (
            geography not in GEOGRAPHIES
            or source_crop not in CROP_SLUGS
            or stock_type not in STOCK_TYPES
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
        snapshot_period, reference_date = _snapshot_fields(reference_period)
        yield {
            "publisher": metadata.publisher,
            "source_table": metadata.source_table,
            "product_id": metadata.product_id,
            "source_url": metadata.source_url,
            "release_date": metadata.release_date,
            "retrieved_at": metadata.retrieved_at,
            "reference_period": reference_period,
            "reference_date": reference_date,
            "snapshot_period": snapshot_period,
            "commodity": CROP_SLUGS[source_crop],
            "source_crop": source_crop,
            "geography": geography,
            "dguid": row.get("DGUID", "").strip(),
            "stock_type": stock_type,
            "original_value": original_value,
            "original_unit": original_unit,
            "scalar_factor": scalar_factor,
            "normalized_tonnes": normalized_tonnes,
            "normalized_unit": "tonnes",
            "observation_status": _observation_status(
                reference_period, geography, stock_type
            ),
            "status_marker": status_marker,
            "symbol": row.get("SYMBOL", "").strip(),
            "terminated": row.get("TERMINATED", "").strip(),
            "decimals": row.get("DECIMALS", "").strip(),
            "vector": row.get("VECTOR", "").strip(),
            "coordinate": row.get("COORDINATE", "").strip(),
        }


def process_archive(
    archive: str | Path, output: str | Path, metadata: DownloadMetadata
) -> int:
    """Filter and normalize the configured stocks slice from a local ZIP."""
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
                        keys: set[tuple[str, str, str, str]] = set()
                        for row in normalize_rows(reader, metadata):
                            key = (
                                row["reference_period"],
                                row["commodity"],
                                row["geography"],
                                row["stock_type"],
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
        description="Download and normalize Statistics Canada table 32-10-0007-01."
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
