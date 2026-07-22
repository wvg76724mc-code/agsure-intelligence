from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from agsure.crop_conditions.common import atomic_write_text, sha256_file
from agsure.weather.common import (
    ARTIFACT_MANIFEST_VERSION,
    GENERATION_MANIFEST,
    OUTPUT_FIELDS,
    PUBLICATION_VERSION,
    SCHEMA_VERSION,
    WeatherObservation,
    validate_observations,
)


@dataclass(frozen=True)
class GenerationPaths:
    generation: str
    directory: Path
    artifact: Path
    artifact_manifest: Path


def current_pointer_path(output: Path) -> Path:
    return output.with_suffix(".CURRENT")


def resolve_current_generation(
    output: Path, *, allow_missing: bool = False
) -> GenerationPaths | None:
    pointer_path = current_pointer_path(output)
    if not pointer_path.exists():
        if allow_missing:
            return None
        raise ValueError("weather CURRENT pointer is missing")
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError("weather CURRENT pointer is malformed") from exc
    if not isinstance(pointer, dict):
        raise ValueError("weather CURRENT pointer is malformed")
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
        raise ValueError("weather CURRENT pointer is malformed")
    generation_dir = (pointer_path.parent / relative_target).resolve()
    if generation_dir.name != generation or not generation_dir.is_dir():
        raise ValueError("weather CURRENT target does not exist or is mismatched")
    manifest_path = generation_dir / GENERATION_MANIFEST
    if not manifest_path.is_file() or sha256_file(manifest_path) != manifest_digest:
        raise ValueError("weather CURRENT generation manifest is mismatched")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError("weather generation manifest is malformed") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("publication_version") != PUBLICATION_VERSION
        or manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("generation") != generation
        or not isinstance(manifest.get("files"), dict)
    ):
        raise ValueError("weather generation manifest is mismatched")
    files = manifest["files"]
    actual_files = {
        candidate.relative_to(generation_dir).as_posix()
        for candidate in generation_dir.rglob("*")
        if candidate.is_file() and candidate.name != GENERATION_MANIFEST
    }
    if set(files) != actual_files:
        raise ValueError("weather CURRENT generation is partial or unmanifested")
    for relative, expected_digest in files.items():
        relative_path = Path(relative)
        if (
            not isinstance(relative, str)
            or not isinstance(expected_digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None
            or relative_path.is_absolute()
            or ".." in relative_path.parts
            or not (generation_dir / relative_path).is_file()
            or sha256_file(generation_dir / relative_path) != expected_digest
        ):
            raise ValueError("weather CURRENT generation file is mismatched")
    artifact = generation_dir / "processed" / output.name
    artifact_manifest = artifact.with_suffix(".manifest.json")
    required = {
        artifact.relative_to(generation_dir).as_posix(),
        artifact_manifest.relative_to(generation_dir).as_posix(),
    }
    if not required.issubset(files):
        raise ValueError("weather CURRENT generation is missing processed outputs")
    return GenerationPaths(generation, generation_dir, artifact, artifact_manifest)


def _from_row(row: dict[str, str]) -> WeatherObservation:
    return WeatherObservation(**row)


def read_artifact(path: Path) -> list[dict[str, str]]:
    generation = resolve_current_generation(path)
    assert generation is not None
    artifact_bytes = generation.artifact.read_bytes()
    try:
        manifest = json.loads(generation.artifact_manifest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError("weather artifact manifest is invalid") from exc
    digest = hashlib.sha256(artifact_bytes).hexdigest()
    if (
        not isinstance(manifest, dict)
        or manifest.get("manifest_version") != ARTIFACT_MANIFEST_VERSION
        or manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("artifact") != generation.artifact.name
        or manifest.get("artifact_sha256") != digest
        or manifest.get("generation_identifier") != generation.generation
    ):
        raise ValueError("weather artifact and manifest generations do not match")
    try:
        text = artifact_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("weather artifact is not UTF-8") from exc
    with io.StringIO(text, newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != OUTPUT_FIELDS:
            raise ValueError("weather artifact schema does not exactly match v0.8")
        rows = list(reader)
    if manifest.get("row_count") != len(rows):
        raise ValueError("weather artifact row count does not match its manifest")
    observations = [_from_row(row) for row in rows]
    validate_observations(observations, expected_generation=generation.generation)
    return rows


def publish_current_pointer(
    output: Path, generation_dir: Path, generation: str,
    generation_manifest_sha256: str,
) -> None:
    pointer = current_pointer_path(output)
    relative_generation = os.path.relpath(generation_dir, pointer.parent)
    atomic_write_text(pointer, json.dumps({
        "publication_version": PUBLICATION_VERSION,
        "generation": generation,
        "generation_path": Path(relative_generation).as_posix(),
        "generation_manifest_sha256": generation_manifest_sha256,
    }, indent=2) + "\n")
