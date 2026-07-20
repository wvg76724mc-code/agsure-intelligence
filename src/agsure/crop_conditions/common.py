from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import tempfile
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Sequence


PARSER_VERSION = "0.7.0"
ARTIFACT_MANIFEST_VERSION = 1
PUBLICATION_VERSION = 1
GENERATION_MANIFEST = "generation.json"
PROVINCE_REGION_PAIRS = {
    "Alberta": (
        ("Alberta", "provincial"), ("South", "south"), ("Central", "central"),
        ("N East", "north-east"), ("N West", "north-west"), ("Peace", "peace"),
    ),
    "Saskatchewan": (
        ("Provincial", "provincial"), ("South East", "south-east"),
        ("South West", "south-west"), ("East Central", "east-central"),
        ("West Central", "west-central"), ("North East", "north-east"),
        ("North West", "north-west"),
    ),
    "Manitoba": (
        ("Southwest", "southwest"), ("Northwest", "northwest"),
        ("Central", "central"), ("Eastern", "eastern"),
        ("Interlake", "interlake"),
    ),
}
OUTPUT_FIELDS = (
    "publisher",
    "source_program",
    "source_report_title",
    "source_url",
    "source_document_url",
    "source_document_sha256",
    "release_date",
    "retrieved_at",
    "reporting_period_start",
    "reporting_period_end",
    "crop_year",
    "province",
    "source_region",
    "source_region_id",
    "geography_level",
    "commodity",
    "source_crop",
    "observation_type",
    "source_measure",
    "category",
    "source_value",
    "value",
    "source_unit",
    "unit",
    "baseline_type",
    "baseline_period",
    "observation_status",
    "extraction_method",
    "source_page",
    "source_table",
    "source_section",
    "source_note",
    "revision_marker",
    "parser_version",
)


@dataclass(frozen=True)
class ReportMetadata:
    publisher: str
    source_program: str
    source_report_title: str
    source_url: str
    source_document_url: str
    source_document_sha256: str
    release_date: str
    retrieved_at: str
    reporting_period_start: str
    reporting_period_end: str
    crop_year: str
    province: str
    extraction_method: str = "embedded_pdf_text"
    revision_marker: str = ""


@dataclass(frozen=True)
class CropConditionObservation:
    publisher: str
    source_program: str
    source_report_title: str
    source_url: str
    source_document_url: str
    source_document_sha256: str
    release_date: str
    retrieved_at: str
    reporting_period_start: str
    reporting_period_end: str
    crop_year: str
    province: str
    source_region: str
    source_region_id: str
    geography_level: str
    commodity: str
    source_crop: str
    observation_type: str
    source_measure: str
    category: str
    source_value: str
    value: str
    source_unit: str
    unit: str
    baseline_type: str
    baseline_period: str
    observation_status: str
    extraction_method: str
    source_page: str
    source_table: str
    source_section: str
    source_note: str
    revision_marker: str
    parser_version: str = PARSER_VERSION

    def as_row(self) -> dict[str, str]:
        return asdict(self)


def parser_error(province: str, report_url: str, expected: str, locator: str) -> ValueError:
    return ValueError(
        f"{province} parser failed for {report_url}: expected {expected}; "
        f"failed locator {locator!r}"
    )


def observation_key(item: CropConditionObservation) -> tuple[str, ...]:
    return (
        item.province,
        item.source_region_id,
        item.commodity,
        item.observation_type,
        item.source_measure,
        item.category,
        item.unit,
        item.baseline_type,
        item.baseline_period,
        item.reporting_period_start,
        item.reporting_period_end,
    )


def validate_observations(
    observations: Sequence[CropConditionObservation], *, rounding_tolerance: Decimal = Decimal("1")
) -> None:
    keys: set[tuple[str, ...]] = set()
    for item in observations:
        key = observation_key(item)
        if key in keys:
            raise ValueError(f"Duplicate crop-condition normalized key: {key!r}")
        keys.add(key)
        region_pair = (item.source_region, item.source_region_id)
        if region_pair not in PROVINCE_REGION_PAIRS.get(item.province, ()):
            raise ValueError(
                f"Region {item.source_region!r} ({item.source_region_id!r}) is not "
                f"valid for {item.province}"
            )
        if item.unit != "percent" or item.source_unit != "%":
            raise ValueError(f"Unexpected crop-condition unit for {key!r}")
        if item.value:
            try:
                value = Decimal(item.value)
            except InvalidOperation as exc:
                raise ValueError(f"Nonnumeric normalized value for {key!r}") from exc
            if not value.is_finite() or value < 0 or value > 100:
                raise ValueError(f"Percentage outside 0-100 for {key!r}")

    expected = {"excellent", "good", "fair", "poor", "very poor"}
    groups: dict[tuple[str, ...], list[CropConditionObservation]] = {}
    for item in observations:
        if (
            item.observation_type != "crop-condition"
            or not item.category
            or item.category == "good-to-excellent"
        ):
            continue
        group = observation_key(item)
        # Remove category only. The exact source measure remains part of the
        # distribution identity so differently labelled measures never combine.
        group = group[:5] + group[6:]
        groups.setdefault(group, []).append(item)
    for identity, items in groups.items():
        categories = {item.category for item in items}
        if categories != expected:
            raise ValueError(
                f"Unexpected crop-condition categories for {identity!r}: "
                f"{sorted(categories)!r}"
            )
        values = [Decimal(item.value) for item in items if item.value]
        if values and len(values) != len(items):
            raise ValueError(f"Partially unavailable category distribution for {identity!r}")
        if values and abs(sum(values) - Decimal("100")) > rounding_tolerance:
            raise ValueError(
                f"Crop-condition categories total {sum(values)} for {identity!r}; "
                f"tolerance is {rounding_tolerance} percentage point"
            )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fsync_directory(path: Path) -> None:
    """Persist directory-entry changes where the platform supports it."""
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def copy_file_fsynced(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as source_handle, destination.open("xb") as destination_handle:
        shutil.copyfileobj(source_handle, destination_handle)
        destination_handle.flush()
        os.fsync(destination_handle.fileno())
    fsync_directory(destination.parent)


@dataclass
class PendingDocument:
    path: Path
    metadata: dict[str, str]
    destination: Path
    metadata_path: Path
    pending: bool

    def promote(self) -> None:
        if not self.pending:
            return
        self.path.replace(self.destination)
        fsync_directory(self.destination.parent)
        atomic_write_text(self.metadata_path, json.dumps(self.metadata, indent=2) + "\n")
        self.path = self.destination
        self.pending = False

    def discard(self) -> None:
        if self.pending:
            self.path.unlink(missing_ok=True)
            self.pending = False


def download_document(
    url: str, cache_dir: Path, filename: str, *, force: bool = False
) -> PendingDocument:
    cache_dir.mkdir(parents=True, exist_ok=True)
    destination = cache_dir / filename
    metadata_path = cache_dir / f"{filename}.retrieval.json"
    if destination.exists() and metadata_path.exists() and not force:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if sha256_file(destination) != metadata["sha256"]:
            raise ValueError(f"Cached document digest does not match {metadata_path}")
        return PendingDocument(destination, metadata, destination, metadata_path, False)
    request = urllib.request.Request(
        url, headers={"User-Agent": "AgSure-Intelligence/0.7 (+official crop reports)"}
    )
    retrieved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with tempfile.NamedTemporaryFile(dir=cache_dir, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                shutil.copyfileobj(response, handle)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    digest = sha256_file(temporary)
    metadata = {"source_url": url, "retrieved_at": retrieved_at, "sha256": digest}
    # The caller must extract and parse the staged document before promotion.
    return PendingDocument(temporary, metadata, destination, metadata_path, True)


def extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "PDF ingestion requires the crop-conditions extra: "
            "python -m pip install -e '.[crop-conditions]'"
        ) from exc
    reader = PdfReader(path)
    pages = [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]
    if not pages or not all(page.strip() for page in pages):
        raise ValueError(f"Embedded PDF text is missing from {path}; OCR is not used")
    return "\n\f\n".join(pages)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        fsync_directory(path.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def write_observations_atomic(
    path: Path,
    observations: Iterable[CropConditionObservation],
    *,
    manifest_data: dict[str, object] | None = None,
) -> None:
    rows = list(observations)
    if not rows:
        raise ValueError("Refusing to overwrite crop-condition artifact with no observations")
    validate_observations(rows)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=OUTPUT_FIELDS)
    writer.writeheader()
    writer.writerows(item.as_row() for item in rows)
    artifact_text = buffer.getvalue()
    artifact_sha256 = hashlib.sha256(artifact_text.encode("utf-8")).hexdigest()
    manifest = {
        "manifest_version": ARTIFACT_MANIFEST_VERSION,
        "artifact": path.name,
        "artifact_sha256": artifact_sha256,
        "generation": f"sha256:{artifact_sha256}",
        "row_count": len(rows),
    }
    if manifest_data:
        manifest["ingestion"] = manifest_data

    # Either replacement may be interrupted, so readers verify this shared
    # generation hash and reject an unmatched pair rather than exposing it.
    atomic_write_text(path, artifact_text)
    atomic_write_text(
        path.with_suffix(".manifest.json"), json.dumps(manifest, indent=2) + "\n"
    )


def current_pointer_path(output: Path) -> Path:
    return output.with_suffix(".CURRENT")


def write_generation_manifest(generation_dir: Path, generation: str) -> str:
    files: dict[str, str] = {}
    for candidate in sorted(generation_dir.rglob("*")):
        if candidate.is_file() and candidate.name != GENERATION_MANIFEST:
            relative = candidate.relative_to(generation_dir).as_posix()
            files[relative] = sha256_file(candidate)
    manifest = {
        "publication_version": PUBLICATION_VERSION,
        "generation": generation,
        "files": files,
    }
    manifest_path = generation_dir / GENERATION_MANIFEST
    atomic_write_text(manifest_path, json.dumps(manifest, indent=2) + "\n")
    for directory, _, filenames in os.walk(generation_dir, topdown=False):
        directory_path = Path(directory)
        for filename in filenames:
            with (directory_path / filename).open("rb") as handle:
                os.fsync(handle.fileno())
        fsync_directory(directory_path)
    return sha256_file(manifest_path)


def finalize_generation(staging_dir: Path, generation_dir: Path) -> None:
    if generation_dir.exists():
        raise FileExistsError(f"Crop-condition generation already exists: {generation_dir}")
    staging_dir.replace(generation_dir)
    fsync_directory(generation_dir.parent)


def publish_current_pointer(
    output: Path,
    generation_dir: Path,
    generation: str,
    generation_manifest_sha256: str,
) -> None:
    pointer = current_pointer_path(output)
    relative_generation = os.path.relpath(generation_dir, pointer.parent)
    payload = {
        "publication_version": PUBLICATION_VERSION,
        "generation": generation,
        "generation_path": Path(relative_generation).as_posix(),
        "generation_manifest_sha256": generation_manifest_sha256,
    }
    atomic_write_text(pointer, json.dumps(payload, indent=2) + "\n")


def new_generation_id() -> str:
    return uuid.uuid4().hex
