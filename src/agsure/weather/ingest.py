from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from agsure.crop_conditions.common import (
    atomic_write_text,
    copy_file_fsynced,
    fsync_directory,
    new_generation_id,
    sha256_file,
)
from agsure.weather.artifact import (
    publish_current_pointer,
    resolve_current_generation,
)
from agsure.weather.common import (
    ARTIFACT_MANIFEST_VERSION,
    GENERATION_MANIFEST,
    PUBLICATION_VERSION,
    SCHEMA_VERSION,
    WeatherObservation,
    artifact_text,
    parse_daily_response,
    validate_station_response,
)
from agsure.weather.config import STATIONS, StationContract


DEFAULT_CACHE = Path("data/raw/weather")
DEFAULT_OUTPUT = Path("data/processed/weather.csv")
DEFAULT_START = date(2024, 1, 1)
DEFAULT_END = date(2025, 12, 31)
MAX_DAYS = 731
API_ROOT = "https://api.weather.gc.ca/collections"
USER_AGENT = "AgSure-Intelligence/0.8 (+official ECCC historical daily weather)"


@dataclass(frozen=True)
class StationResult:
    climate_id: str
    station_name: str
    source_dates_returned: int
    artifact_rows: int
    missing_source_dates: int
    source_sha256: str


def station_url(station: StationContract) -> str:
    return (
        f"{API_ROOT}/climate-stations/items?f=json&"
        f"CLIMATE_IDENTIFIER={station.climate_id}&limit=10"
    )


def daily_url(station: StationContract, start: date, end: date) -> str:
    return (
        f"{API_ROOT}/climate-daily/items?f=json&"
        f"CLIMATE_IDENTIFIER={station.climate_id}&"
        f"datetime={start.isoformat()}%2F{end.isoformat()}&limit=1000"
    )


def validate_range(start: date, end: date) -> None:
    if end < start:
        raise ValueError("Weather end date precedes start date")
    if (end - start).days + 1 > MAX_DAYS:
        raise ValueError(f"Weather ingestion is limited to {MAX_DAYS} days")
    if end >= date.today():
        raise ValueError("Weather ingestion end date must be a completed prior day")
    if any(start < date.fromisoformat(station.daily_first_date) for station in STATIONS):
        raise ValueError("Weather range predates a configured station's daily operation")


def _retrieved_at() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _download_json(url: str, destination: Path) -> tuple[object, dict[str, object]]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent, prefix=f".{destination.name}."
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            with urllib.request.urlopen(request, timeout=120) as response:
                content_type = response.headers.get_content_type()
                if content_type not in {"application/json", "application/geo+json"}:
                    raise ValueError(
                        f"Unexpected ECCC content type {content_type!r} for {url}"
                    )
                while chunk := response.read(1024 * 1024):
                    handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        raw = temporary.read_bytes()
        if not raw.lstrip().startswith(b"{"):
            raise ValueError("ECCC response is not a JSON object")
        payload = json.loads(raw)
        temporary.replace(destination)
        fsync_directory(destination.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    metadata: dict[str, object] = {
        "source_url": url, "retrieved_at": _retrieved_at(),
        "sha256": hashlib.sha256(raw).hexdigest(), "byte_count": len(raw),
        "content_type": content_type,
    }
    atomic_write_text(
        destination.with_suffix(destination.suffix + ".retrieval.json"),
        json.dumps(metadata, indent=2) + "\n",
    )
    return payload, metadata


def _read_cached_json(
    source: Path, destination: Path, *, expected_url: str,
) -> tuple[object, dict[str, object]]:
    metadata_source = source.with_suffix(source.suffix + ".retrieval.json")
    try:
        metadata = json.loads(metadata_source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Weather cached retrieval metadata is malformed") from exc
    if (
        not isinstance(metadata, dict)
        or metadata.get("source_url") != expected_url
        or metadata.get("sha256") != sha256_file(source)
        or metadata.get("byte_count") != source.stat().st_size
        or metadata.get("content_type") not in {"application/json", "application/geo+json"}
        or not isinstance(metadata.get("retrieved_at"), str)
    ):
        raise ValueError("Weather cached retrieval metadata is mismatched")
    copy_file_fsynced(source, destination)
    atomic_write_text(
        destination.with_suffix(destination.suffix + ".retrieval.json"),
        json.dumps(metadata, indent=2) + "\n",
    )
    return json.loads(destination.read_text(encoding="utf-8")), metadata


def _stage_json(
    filename: str, url: str, destination_dir: Path, previous_dir: Path | None,
    *, force: bool,
) -> tuple[object, dict[str, object]]:
    destination = destination_dir / filename
    if not force and previous_dir is not None:
        source = previous_dir / filename
        if source.is_file() and source.with_suffix(source.suffix + ".retrieval.json").is_file():
            return _read_cached_json(source, destination, expected_url=url)
    return _download_json(url, destination)


def _write_processed(
    path: Path, observations: list[WeatherObservation], generation: str,
    results: list[StationResult], start: date, end: date,
) -> None:
    text, row_count, digest = artifact_text(observations)
    atomic_write_text(path, text)
    atomic_write_text(path.with_suffix(".manifest.json"), json.dumps({
        "manifest_version": ARTIFACT_MANIFEST_VERSION,
        "schema_version": SCHEMA_VERSION,
        "artifact": path.name,
        "artifact_sha256": digest,
        "generation_identifier": generation,
        "row_count": row_count,
        "ingestion": {
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            "station_results": [result.__dict__ for result in results],
        },
    }, indent=2) + "\n")


def _write_generation_manifest(directory: Path, generation: str) -> str:
    files = {
        candidate.relative_to(directory).as_posix(): sha256_file(candidate)
        for candidate in sorted(directory.rglob("*"))
        if candidate.is_file() and candidate.name != GENERATION_MANIFEST
    }
    path = directory / GENERATION_MANIFEST
    atomic_write_text(path, json.dumps({
        "publication_version": PUBLICATION_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generation": generation, "files": files,
    }, indent=2) + "\n")
    for child, _, filenames in os.walk(directory, topdown=False):
        child_path = Path(child)
        for filename in filenames:
            with (child_path / filename).open("rb") as handle:
                os.fsync(handle.fileno())
        fsync_directory(child_path)
    return sha256_file(path)


def ingest(
    cache_dir: Path, output: Path, *, start: date = DEFAULT_START,
    end: date = DEFAULT_END, force: bool = False,
) -> list[StationResult]:
    validate_range(start, end)
    current = resolve_current_generation(output, allow_missing=True)
    previous_raw = None if current is None else current.directory / "sources"
    generation = new_generation_id()
    generation_root = cache_dir / "generations"
    generation_root.mkdir(parents=True, exist_ok=True)
    staging = generation_root / f".staging-{generation}"
    destination = generation_root / generation
    staging.mkdir()
    observations: list[WeatherObservation] = []
    results: list[StationResult] = []
    try:
        for station in STATIONS:
            station_dir = staging / "sources" / station.climate_id
            previous_station = None if previous_raw is None else previous_raw / station.climate_id
            station_payload, _ = _stage_json(
                "station.json", station_url(station), station_dir, previous_station,
                force=force,
            )
            validate_station_response(station_payload, station)
            source_url = daily_url(station, start, end)
            daily_payload, retrieval = _stage_json(
                "daily.json", source_url, station_dir, previous_station,
                force=force,
            )
            station_rows = parse_daily_response(
                daily_payload, station, start, end,
                retrieved_at=str(retrieval["retrieved_at"]), source_url=source_url,
                generation=generation,
            )
            observations.extend(station_rows)
            returned = int(daily_payload["numberReturned"])
            results.append(StationResult(
                station.climate_id, station.name, returned, len(station_rows),
                (end - start).days + 1 - returned, str(retrieval["sha256"]),
            ))
        _write_processed(
            staging / "processed" / output.name, observations, generation,
            results, start, end,
        )
        generation_digest = _write_generation_manifest(staging, generation)
        if destination.exists():
            raise FileExistsError(f"Weather generation already exists: {destination}")
        staging.replace(destination)
        fsync_directory(destination.parent)
        publish_current_pointer(output, destination, generation, generation_digest)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest official ECCC daily observations for approved stations"
    )
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--start-date", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--end-date", type=date.fromisoformat, default=DEFAULT_END)
    parser.add_argument(
        "--force", action="store_true",
        help="retrieve a fresh official source vintage instead of reusing CURRENT sources",
    )
    args = parser.parse_args()
    for result in ingest(
        args.cache_dir, args.output, start=args.start_date,
        end=args.end_date, force=args.force,
    ):
        print(
            f"{result.station_name} ({result.climate_id}): "
            f"source_dates={result.source_dates_returned}; "
            f"artifact_rows={result.artifact_rows}; "
            f"missing_source_dates={result.missing_source_dates}; "
            f"sha256={result.source_sha256}"
        )


if __name__ == "__main__":
    main()
