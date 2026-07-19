from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import re
import shutil
import tempfile
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Iterator, Mapping

from agsure.commodities import COMMODITIES


PUBLISHER = "Statistics Canada"
SOURCE_TABLE = "32-10-0359-01"
PRODUCT_ID = "32100359"
SOURCE_URL = "https://www150.statcan.gc.ca/n1/en/tbl/csv/32100359-eng.zip"
DOWNLOAD_URL = "https://www150.statcan.gc.ca/n1/tbl/csv/32100359-eng.zip"
TABLE_URL = "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3210035901"
DEFAULT_CACHE_DIR = Path("data/raw/statcan")
DEFAULT_OUTPUT = Path("data/processed/statcan_crop_production.csv")

GEOGRAPHIES = {"Canada", "Alberta", "Saskatchewan", "Manitoba"}
CROP_SLUGS = {definition.statcan_name: slug for slug, definition in COMMODITIES.items()}


@dataclass(frozen=True)
class MetricDefinition:
    slug: str
    source_unit: str
    unit: str
    unit_multiplier: Decimal


METRICS = {
    "Seeded area (hectares)": MetricDefinition(
        "seeded-area", "Hectares", "hectares", Decimal("1")
    ),
    "Harvested area (hectares)": MetricDefinition(
        "harvested-area", "Hectares", "hectares", Decimal("1")
    ),
    "Average yield (kilograms per hectare)": MetricDefinition(
        "yield", "Kilograms per hectare", "tonnes per hectare", Decimal("0.001")
    ),
    "Production (metric tonnes)": MetricDefinition(
        "production", "Metric tonnes", "tonnes", Decimal("1")
    ),
}

SCALAR_MULTIPLIERS = {
    "units": Decimal("1"),
    "tens": Decimal("10"),
    "hundreds": Decimal("100"),
    "thousands": Decimal("1000"),
    "millions": Decimal("1000000"),
    "billions": Decimal("1000000000"),
}

OUTPUT_FIELDS = (
    "publisher",
    "source_table",
    "product_id",
    "source_url",
    "release_date",
    "retrieved_at",
    "reference_period",
    "commodity",
    "source_crop",
    "geography",
    "dguid",
    "metric",
    "source_value",
    "source_unit",
    "scalar_factor",
    "value",
    "unit",
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
    "Type of crop",
    "Harvest disposition",
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


@dataclass(frozen=True)
class DownloadMetadata:
    publisher: str
    source_table: str
    product_id: str
    source_url: str
    release_date: str
    retrieved_at: str
    sha256: str
    archive: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_decimal(value: Decimal) -> str:
    return format(value, "f")


def _parse_release_date(page: str) -> str:
    visible_text = html.unescape(re.sub(r"<[^>]+>", " ", page))
    match = re.search(
        r"Release date:\s*(\d{4}-\d{2}-\d{2})", visible_text, re.IGNORECASE
    )
    if not match:
        raise ValueError("Could not determine the Statistics Canada release date")
    return date.fromisoformat(match.group(1)).isoformat()


def _request(url: str):
    request = urllib.request.Request(
        url, headers={"User-Agent": "AgSure-Intelligence/0.2 (+source ingestion)"}
    )
    return urllib.request.urlopen(request, timeout=120)


def download_table(
    cache_dir: str | Path = DEFAULT_CACHE_DIR, *, force: bool = False
) -> tuple[Path, DownloadMetadata]:
    """Download and cache the full StatCan archive plus retrieval metadata."""
    directory = Path(cache_dir)
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / f"{PRODUCT_ID}-eng.zip"
    metadata_path = directory / f"{PRODUCT_ID}-retrieval.json"

    if archive.exists() and metadata_path.exists() and not force:
        stored = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata = DownloadMetadata(**stored)
        digest = _sha256(archive)
        if digest != metadata.sha256:
            raise ValueError(
                f"Cached archive digest does not match {metadata_path}; use --force"
            )
        return archive, metadata

    retrieved_at = _utc_now().isoformat().replace("+00:00", "Z")
    with _request(TABLE_URL) as response:
        page = response.read().decode("utf-8", errors="replace")
    release_date = _parse_release_date(page)

    with tempfile.NamedTemporaryFile(
        dir=directory, suffix=".zip", delete=False
    ) as temp:
        temporary_archive = Path(temp.name)
        try:
            with _request(DOWNLOAD_URL) as response:
                shutil.copyfileobj(response, temp)
        except BaseException:
            temporary_archive.unlink(missing_ok=True)
            raise

    try:
        with zipfile.ZipFile(temporary_archive) as bundle:
            if bundle.testzip() is not None:
                raise ValueError(
                    "Downloaded Statistics Canada ZIP failed integrity check"
                )
        digest = _sha256(temporary_archive)
        temporary_archive.replace(archive)
    except BaseException:
        temporary_archive.unlink(missing_ok=True)
        raise

    metadata = DownloadMetadata(
        publisher=PUBLISHER,
        source_table=SOURCE_TABLE,
        product_id=PRODUCT_ID,
        source_url=SOURCE_URL,
        release_date=release_date,
        retrieved_at=retrieved_at,
        sha256=digest,
        archive=archive.name,
    )
    metadata_path.write_text(
        json.dumps(asdict(metadata), indent=2) + "\n", encoding="utf-8"
    )
    return archive, metadata


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scalar_multiplier(label: str) -> Decimal:
    try:
        return SCALAR_MULTIPLIERS[label.strip().lower()]
    except KeyError as exc:
        raise ValueError(f"Unsupported scalar factor {label!r}") from exc


def normalize_rows(
    rows: Iterable[Mapping[str, str]], metadata: DownloadMetadata
) -> Iterator[dict[str, str]]:
    for row_number, row in enumerate(rows, start=2):
        geography = row.get("GEO", "").strip()
        source_crop = row.get("Type of crop", "").strip()
        disposition = row.get("Harvest disposition", "").strip()
        if (
            geography not in GEOGRAPHIES
            or source_crop not in CROP_SLUGS
            or disposition not in METRICS
        ):
            continue

        metric = METRICS[disposition]
        source_unit = row.get("UOM", "").strip()
        if source_unit != metric.source_unit:
            continue

        scalar_factor = row.get("SCALAR_FACTOR", "").strip()
        scalar_multiplier = _scalar_multiplier(scalar_factor)
        source_value = row.get("VALUE", "").strip()
        normalized_value = ""
        if source_value:
            try:
                value = (
                    Decimal(source_value)
                    * scalar_multiplier
                    * metric.unit_multiplier
                )
            except InvalidOperation as exc:
                raise ValueError(
                    f"Invalid VALUE {source_value!r} at source row {row_number}"
                ) from exc
            normalized_value = _format_decimal(value)

        yield {
            "publisher": metadata.publisher,
            "source_table": metadata.source_table,
            "product_id": metadata.product_id,
            "source_url": metadata.source_url,
            "release_date": metadata.release_date,
            "retrieved_at": metadata.retrieved_at,
            "reference_period": row.get("REF_DATE", "").strip(),
            "commodity": CROP_SLUGS[source_crop],
            "source_crop": source_crop,
            "geography": geography,
            "dguid": row.get("DGUID", "").strip(),
            "metric": metric.slug,
            "source_value": source_value,
            "source_unit": source_unit,
            "scalar_factor": scalar_factor,
            "value": normalized_value,
            "unit": metric.unit,
            "observation_status": "estimated",
            "status_marker": row.get("STATUS", "").strip(),
            "symbol": row.get("SYMBOL", "").strip(),
            "terminated": row.get("TERMINATED", "").strip(),
            "decimals": row.get("DECIMALS", "").strip(),
            "vector": row.get("VECTOR", "").strip(),
            "coordinate": row.get("COORDINATE", "").strip(),
        }


def _data_member(bundle: zipfile.ZipFile) -> str:
    candidates = [
        name
        for name in bundle.namelist()
        if name.lower().endswith(".csv") and "metadata" not in name.lower()
    ]
    if len(candidates) != 1:
        raise ValueError(
            "Expected one non-metadata CSV in the Statistics Canada archive; "
            f"found {len(candidates)}"
        )
    return candidates[0]


def process_archive(
    archive: str | Path, output: str | Path, metadata: DownloadMetadata
) -> int:
    """Filter and normalize the requested vertical slice from a StatCan ZIP."""
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
                    rows = normalize_rows(reader, metadata)
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
                        for row in rows:
                            key = (
                                row["reference_period"],
                                row["commodity"],
                                row["geography"],
                                row["metric"],
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
        description="Download and normalize Statistics Canada table 32-10-0359-01."
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
