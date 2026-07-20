from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

from agsure.crop_conditions.common import (
    ARTIFACT_MANIFEST_VERSION,
    GENERATION_MANIFEST,
    OUTPUT_FIELDS,
    PROVINCE_REGION_PAIRS,
    PUBLICATION_VERSION,
    current_pointer_path,
    sha256_file,
)


UNAVAILABLE = "Not available from the selected official crop report"
PROVINCE_REGIONS = PROVINCE_REGION_PAIRS


@dataclass(frozen=True)
class RegionalSeries:
    available: bool
    reason: str
    rows: tuple[dict[str, str], ...]
    latest: dict[str, str] | None


@dataclass(frozen=True)
class PeriodComparison:
    selected: dict[str, str]
    previous: dict[str, str] | None
    change_percentage_points: Decimal | None


@dataclass(frozen=True)
class GenerationPaths:
    generation: str
    directory: Path
    artifact: Path
    artifact_manifest: Path


def resolve_current_generation(
    output: Path, *, allow_missing: bool = False
) -> GenerationPaths | None:
    pointer_path = current_pointer_path(output)
    if not pointer_path.exists():
        if allow_missing:
            return None
        raise ValueError("crop-condition CURRENT pointer is missing")
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError("crop-condition CURRENT pointer is malformed") from exc
    if not isinstance(pointer, dict):
        raise ValueError("crop-condition CURRENT pointer is malformed")
    generation = pointer.get("generation")
    relative_target = pointer.get("generation_path")
    manifest_digest = pointer.get("generation_manifest_sha256")
    if (
        pointer.get("publication_version") != PUBLICATION_VERSION
        or not isinstance(generation, str)
        or re.fullmatch(r"[0-9a-f]{32}", generation) is None
        or not isinstance(relative_target, str)
        or not relative_target
        or Path(relative_target).is_absolute()
        or not isinstance(manifest_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", manifest_digest) is None
    ):
        raise ValueError("crop-condition CURRENT pointer is malformed")
    generation_dir = (pointer_path.parent / relative_target).resolve()
    if generation_dir.name != generation or not generation_dir.is_dir():
        raise ValueError("crop-condition CURRENT target does not exist or is mismatched")
    generation_manifest_path = generation_dir / GENERATION_MANIFEST
    if (
        not generation_manifest_path.is_file()
        or sha256_file(generation_manifest_path) != manifest_digest
    ):
        raise ValueError("crop-condition CURRENT generation manifest is mismatched")
    try:
        generation_manifest = json.loads(
            generation_manifest_path.read_text(encoding="utf-8")
        )
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError("crop-condition generation manifest is malformed") from exc
    if (
        not isinstance(generation_manifest, dict)
        or generation_manifest.get("publication_version") != PUBLICATION_VERSION
        or generation_manifest.get("generation") != generation
        or not isinstance(generation_manifest.get("files"), dict)
    ):
        raise ValueError("crop-condition generation manifest is mismatched")
    files = generation_manifest["files"]
    actual_files = {
        candidate.relative_to(generation_dir).as_posix()
        for candidate in generation_dir.rglob("*")
        if candidate.is_file() and candidate.name != GENERATION_MANIFEST
    }
    if set(files) != actual_files:
        raise ValueError("crop-condition CURRENT generation is partial or unmanifested")
    for relative, expected_digest in files.items():
        if (
            not isinstance(relative, str)
            or not isinstance(expected_digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None
        ):
            raise ValueError("crop-condition CURRENT generation file is mismatched")
        relative_path = Path(relative)
        if (
            relative_path.is_absolute()
            or ".." in relative_path.parts
            or sha256_file(generation_dir / relative_path) != expected_digest
        ):
            raise ValueError("crop-condition CURRENT generation file is mismatched")
    for province in ("alberta", "saskatchewan", "manitoba"):
        province_files = [
            relative for relative in files if relative.startswith(f"documents/{province}/")
        ]
        if (
            len([name for name in province_files if name.endswith(".pdf")]) != 1
            or len([name for name in province_files if name.endswith(".retrieval.json")])
            != 1
        ):
            raise ValueError(
                f"crop-condition CURRENT generation is missing {province} documents"
            )
    artifact = generation_dir / "processed" / output.name
    artifact_manifest = artifact.with_suffix(".manifest.json")
    required = {
        artifact.relative_to(generation_dir).as_posix(),
        artifact_manifest.relative_to(generation_dir).as_posix(),
    }
    if not required.issubset(files):
        raise ValueError("crop-condition CURRENT generation is missing processed outputs")
    return GenerationPaths(generation, generation_dir, artifact, artifact_manifest)


def read_artifact(path: Path) -> list[dict[str, str]]:
    generation = resolve_current_generation(path)
    assert generation is not None
    manifest_path = generation.artifact_manifest
    artifact_bytes = generation.artifact.read_bytes()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError("crop-condition artifact manifest is invalid") from exc
    if not isinstance(manifest, dict):
        raise ValueError("crop-condition artifact manifest is invalid")
    digest = hashlib.sha256(artifact_bytes).hexdigest()
    if (
        manifest.get("manifest_version") != ARTIFACT_MANIFEST_VERSION
        or manifest.get("artifact") != generation.artifact.name
        or manifest.get("artifact_sha256") != digest
        or manifest.get("generation") != f"sha256:{digest}"
    ):
        raise ValueError("crop-condition artifact and manifest generations do not match")
    with io.StringIO(artifact_bytes.decode("utf-8"), newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(OUTPUT_FIELDS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(
                "crop-condition artifact is missing required columns: "
                + ", ".join(sorted(missing))
            )
        rows = list(reader)
    if manifest.get("row_count") != len(rows):
        raise ValueError("crop-condition artifact row count does not match its manifest")
    keys = [
        tuple(row[field] for field in (
            "province", "source_region_id", "commodity", "observation_type",
            "source_measure", "category", "unit", "baseline_type",
            "baseline_period", "reporting_period_start", "reporting_period_end",
        ))
        for row in rows
    ]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate crop-condition normalized keys")
    return rows


def options(rows: Iterable[dict[str, str]], field: str, **filters: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            row[field]
            for row in rows
            if row[field] and all(row.get(key) == value for key, value in filters.items())
        )
    )


def select_series(
    rows: Iterable[dict[str, str]], *, province: str, source_region_id: str,
    commodity: str, observation_type: str, source_measure: str, category: str,
) -> RegionalSeries:
    selected = [
        row for row in rows
        if row["province"] == province
        and row["source_region_id"] == source_region_id
        and row["commodity"] == commodity
        and row["observation_type"] == observation_type
        and row["source_measure"] == source_measure
        and row["category"] == category
    ]
    if not selected:
        identity = "/".join((province, source_region_id, commodity, source_measure, category))
        return RegionalSeries(False, f"{UNAVAILABLE}: {identity}", (), None)
    selected.sort(key=lambda row: (row["reporting_period_end"], row["release_date"]))
    latest = selected[-1]
    available = bool(latest["value"])
    comparison_identity = {
        (
            row["province"], row["source_region"], row["source_region_id"],
            row["commodity"], row["observation_type"], row["source_measure"],
            row["category"], row["unit"], row["baseline_type"],
            row["baseline_period"], row["source_program"],
        )
        for row in selected
    }
    if len(comparison_identity) != 1:
        raise ValueError("Selected crop-condition rows contain incompatible series identities")
    reason = "" if available else f"{UNAVAILABLE}: source status is {latest['observation_status']}"
    return RegionalSeries(available, reason, tuple(selected), latest)


def compare_selected_period(
    rows: Iterable[dict[str, str]], reporting_period_end: str
) -> PeriodComparison:
    candidates = [row for row in rows if row["reporting_period_end"] == reporting_period_end]
    if len(candidates) != 1:
        raise ValueError("Selected reporting period does not identify exactly one observation")
    selected = candidates[0]
    identity_fields = (
        "province", "source_region", "source_region_id", "commodity",
        "observation_type", "source_measure", "category", "unit",
        "baseline_type", "baseline_period", "source_program",
    )
    target = date.fromisoformat(reporting_period_end) - timedelta(days=7)
    previous_candidates = [
        row
        for row in rows
        if date.fromisoformat(row["reporting_period_end"]) == target
        and all(row[field] == selected[field] for field in identity_fields)
    ]
    if len(previous_candidates) > 1:
        raise ValueError("Multiple exact previous crop-condition observations found")
    previous = previous_candidates[0] if previous_candidates else None
    change = None
    if selected["value"] and previous is not None and previous["value"]:
        if selected["unit"] == "percent":
            try:
                change = Decimal(selected["value"]) - Decimal(previous["value"])
            except InvalidOperation as exc:
                raise ValueError("Nonnumeric percentage in crop-condition artifact") from exc
    return PeriodComparison(selected, previous, change)
