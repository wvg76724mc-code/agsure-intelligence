from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from agsure.crop_conditions.common import (
    atomic_write_text,
    copy_file_fsynced,
    fsync_directory,
    new_generation_id,
    sha256_file,
)
from agsure.weather.artifact import publish_current_pointer, resolve_current_generation
from agsure.weather.common import (
    ARTIFACT_MANIFEST_VERSION,
    GENERATION_MANIFEST,
    PUBLICATION_VERSION,
    SCHEMA_VERSION,
    SOURCE_ELEMENTS,
    WeatherObservation,
    artifact_text,
    parse_daily_response,
    validate_station_response,
)
from agsure.weather.config import STATIONS, StationContract


DEFAULT_CACHE = Path("data/raw/weather")
DEFAULT_OUTPUT = Path("data/processed/weather.csv")
DEFAULT_START = date(2024, 1, 1)
MAX_REQUEST_DAYS = 731
API_ROOT = "https://api.weather.gc.ca/collections"
COMPLETED_DAY_TIMEZONE = ZoneInfo("America/Edmonton")
COMPLETED_DAY_TIMEZONE_NAME = "America/Edmonton"
USER_AGENT = "AgSure-Intelligence/0.8 (+official ECCC historical daily weather)"


@dataclass(frozen=True)
class StationResult:
    climate_id: str
    station_name: str
    coverage_start_date: str
    coverage_end_date: str
    retrieved_at: str
    source_dates_returned: int
    artifact_rows: int
    missing_source_dates: int
    omitted_source_dates: tuple[str, ...]
    blank_source_dates: tuple[str, ...]
    daily_source_urls: tuple[str, ...]
    daily_source_sha256: tuple[str, ...]
    latest_available_date_by_element: dict[str, str]
    available_days_by_element: dict[str, int]
    observation_status_counts: dict[str, int]
    source_flag_counts: dict[str, int]


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


def latest_completed_day(
    *, now: datetime | None = None, as_of_date: date | None = None
) -> date:
    """Return yesterday in America/Edmonton, never the current local day.

    ``as_of_date`` is interpreted as a calendar date in the documented timezone.
    It is mutually exclusive with an injected clock so tests cannot ambiguously
    supply two different notions of "now".
    """
    if now is not None and as_of_date is not None:
        raise ValueError("Specify either an injected clock or as_of_date, not both")
    if as_of_date is None:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("Weather clock must be timezone-aware")
        as_of_date = current.astimezone(COMPLETED_DAY_TIMEZONE).date()
    return as_of_date - timedelta(days=1)


def validate_range(start: date, end: date, *, eligible_end: date) -> None:
    if end < start:
        raise ValueError("Weather end date precedes start date")
    if end > eligible_end:
        raise ValueError(
            "Weather ingestion end date must be no later than the completed prior "
            f"day in {COMPLETED_DAY_TIMEZONE_NAME} ({eligible_end.isoformat()})"
        )
    if any(start < date.fromisoformat(station.daily_first_date) for station in STATIONS):
        raise ValueError("Weather range predates a configured station's daily operation")


def _request_ranges(start: date, end: date):
    current = start
    while current <= end:
        chunk_end = min(end, current + timedelta(days=MAX_REQUEST_DAYS - 1))
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


def _retrieved_at(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("Weather retrieval clock must be timezone-aware")
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _download_json(
    url: str, destination: Path, *, retrieved_at: str | None = None
) -> tuple[object, dict[str, object]]:
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
        "source_url": url,
        "retrieved_at": retrieved_at or _retrieved_at(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "byte_count": len(raw),
        "content_type": content_type,
    }
    atomic_write_text(
        destination.with_suffix(destination.suffix + ".retrieval.json"),
        json.dumps(metadata, indent=2) + "\n",
    )
    return payload, metadata


def _read_cached_json(
    source: Path, destination: Path, *, expected_url: str
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
        or metadata.get("content_type")
        not in {"application/json", "application/geo+json"}
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
    filename: str,
    url: str,
    destination_dir: Path,
    previous_dir: Path | None,
    *,
    force: bool,
    retrieved_at: str,
) -> tuple[object, dict[str, object]]:
    destination = destination_dir / filename
    if not force and previous_dir is not None:
        source = previous_dir / filename
        if source.is_file() and source.with_suffix(
            source.suffix + ".retrieval.json"
        ).is_file():
            return _read_cached_json(source, destination, expected_url=url)
    return _download_json(url, destination, retrieved_at=retrieved_at)


def _station_result(
    station: StationContract,
    rows: list[WeatherObservation],
    start: date,
    end: date,
    retrieved_at: str,
    returned_dates: set[str],
    urls: list[str],
    hashes: list[str],
) -> StationResult:
    source_rows = [row for row in rows if row.observation_origin == "source_published"]
    latest: dict[str, str] = {}
    available: dict[str, int] = {}
    for label, (identifier, _, _) in SOURCE_ELEMENTS.items():
        element = [
            row
            for row in source_rows
            if row.source_element_identifier == identifier and row.normalized_value
        ]
        available[label] = len(element)
        latest[label] = max((row.reference_date for row in element), default="")
    all_dates = {
        (start + timedelta(days=offset)).isoformat()
        for offset in range((end - start).days + 1)
    }
    status_counts = Counter(row.observation_status for row in source_rows)
    flag_counts = Counter(row.source_quality_flag for row in source_rows if row.source_quality_flag)
    return StationResult(
        climate_id=station.climate_id,
        station_name=station.name,
        coverage_start_date=start.isoformat(),
        coverage_end_date=end.isoformat(),
        retrieved_at=retrieved_at,
        source_dates_returned=len(returned_dates),
        artifact_rows=len(rows),
        missing_source_dates=len(all_dates - returned_dates),
        omitted_source_dates=tuple(sorted(all_dates - returned_dates)),
        blank_source_dates=tuple(sorted({
            row.reference_date
            for row in source_rows
            if row.observation_status == "unavailable_source_date_blank"
        })),
        daily_source_urls=tuple(urls),
        daily_source_sha256=tuple(hashes),
        latest_available_date_by_element=latest,
        available_days_by_element=available,
        observation_status_counts=dict(sorted(status_counts.items())),
        source_flag_counts=dict(sorted(flag_counts.items())),
    )


def _write_processed(
    path: Path,
    observations: list[WeatherObservation],
    generation: str,
    results: list[StationResult],
    start: date,
    end: date,
    retrieved_at: str = "",
) -> None:
    text, row_count, digest = artifact_text(observations)
    atomic_write_text(path, text)
    atomic_write_text(
        path.with_suffix(".manifest.json"),
        json.dumps(
            {
                "manifest_version": ARTIFACT_MANIFEST_VERSION,
                "schema_version": SCHEMA_VERSION,
                "artifact": path.name,
                "artifact_sha256": digest,
                "generation_identifier": generation,
                "row_count": row_count,
                "retrieved_at": retrieved_at,
                "coverage_start_date": start.isoformat(),
                "coverage_end_date": end.isoformat(),
                "coverage_status": (
                    "partial_year" if end < date(end.year, 12, 31) else "complete_year"
                ),
                "ingestion": {
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "completed_day_timezone": COMPLETED_DAY_TIMEZONE_NAME,
                    "completed_day_rule": "calendar day immediately before local as-of date",
                    "station_results": [asdict(result) for result in results],
                },
            },
            indent=2,
        )
        + "\n",
    )


def _write_generation_manifest(directory: Path, generation: str) -> str:
    files = {
        candidate.relative_to(directory).as_posix(): sha256_file(candidate)
        for candidate in sorted(directory.rglob("*"))
        if candidate.is_file() and candidate.name != GENERATION_MANIFEST
    }
    path = directory / GENERATION_MANIFEST
    atomic_write_text(
        path,
        json.dumps(
            {
                "publication_version": PUBLICATION_VERSION,
                "schema_version": SCHEMA_VERSION,
                "generation": generation,
                "files": files,
            },
            indent=2,
        )
        + "\n",
    )
    for child, _, filenames in os.walk(directory, topdown=False):
        child_path = Path(child)
        for filename in filenames:
            with (child_path / filename).open("rb") as handle:
                os.fsync(handle.fileno())
        fsync_directory(child_path)
    return sha256_file(path)


def _verify_generation(directory: Path, generation: str, digest: str) -> None:
    path = directory / GENERATION_MANIFEST
    if sha256_file(path) != digest:
        raise ValueError("Weather generation manifest changed before publication")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("generation") != generation or not isinstance(manifest.get("files"), dict):
        raise ValueError("Weather generation manifest is mismatched before publication")
    actual = {
        candidate.relative_to(directory).as_posix()
        for candidate in directory.rglob("*")
        if candidate.is_file() and candidate.name != GENERATION_MANIFEST
    }
    if actual != set(manifest["files"]):
        raise ValueError("Weather generation is partial before publication")
    for relative, expected in manifest["files"].items():
        if sha256_file(directory / relative) != expected:
            raise ValueError("Weather generation file changed before publication")


def ingest(
    cache_dir: Path,
    output: Path,
    *,
    start: date = DEFAULT_START,
    end: date | None = None,
    to_latest: bool = False,
    as_of_date: date | None = None,
    now: datetime | None = None,
    force: bool = False,
) -> list[StationResult]:
    if to_latest and end is not None:
        raise ValueError("--to-latest cannot be combined with an explicit end date")
    if as_of_date is not None and not to_latest:
        raise ValueError("--as-of-date requires --to-latest")
    eligible_end = latest_completed_day(now=now, as_of_date=as_of_date)
    if to_latest:
        end = eligible_end
        force = True
    if end is None:
        raise ValueError("Specify an explicit end date or use --to-latest")
    validate_range(start, end, eligible_end=eligible_end)

    current = resolve_current_generation(output, allow_missing=True)
    previous_raw = None if current is None else current.directory / "sources"
    generation = new_generation_id()
    generation_retrieved_at = _retrieved_at(now)
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
            previous_station = (
                None if previous_raw is None else previous_raw / station.climate_id
            )
            station_payload, _ = _stage_json(
                "station.json",
                station_url(station),
                station_dir,
                previous_station,
                force=force,
                retrieved_at=generation_retrieved_at,
            )
            validate_station_response(station_payload, station)
            station_rows: list[WeatherObservation] = []
            returned_dates: set[str] = set()
            urls: list[str] = []
            hashes: list[str] = []
            for chunk_start, chunk_end in _request_ranges(start, end):
                source_url = daily_url(station, chunk_start, chunk_end)
                filename = f"daily-{chunk_start.isoformat()}-{chunk_end.isoformat()}.json"
                daily_payload, retrieval = _stage_json(
                    filename,
                    source_url,
                    station_dir,
                    previous_station,
                    force=force,
                    retrieved_at=generation_retrieved_at,
                )
                parsed = parse_daily_response(
                    daily_payload,
                    station,
                    chunk_start,
                    chunk_end,
                    retrieved_at=str(retrieval["retrieved_at"]),
                    source_url=source_url,
                    generation=generation,
                )
                station_rows.extend(parsed)
                returned_dates.update(
                    str(feature["properties"]["LOCAL_DATE"])[:10]
                    for feature in daily_payload["features"]
                )
                urls.append(source_url)
                hashes.append(str(retrieval["sha256"]))
            observations.extend(station_rows)
            results.append(
                _station_result(
                    station,
                    station_rows,
                    start,
                    end,
                    generation_retrieved_at,
                    returned_dates,
                    urls,
                    hashes,
                )
            )
        _write_processed(
            staging / "processed" / output.name,
            observations,
            generation,
            results,
            start,
            end,
            generation_retrieved_at,
        )
        generation_digest = _write_generation_manifest(staging, generation)
        _verify_generation(staging, generation, generation_digest)
        if destination.exists():
            raise FileExistsError(f"Weather generation already exists: {destination}")
        staging.replace(destination)
        fsync_directory(destination.parent)
        _verify_generation(destination, generation, generation_digest)
        publish_current_pointer(output, destination, generation, generation_digest)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return results


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ingest official ECCC daily observations for approved stations"
    )
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--start-date", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--end-date", type=date.fromisoformat)
    parser.add_argument(
        "--to-latest",
        action="store_true",
        help=(
            "retrieve through the calendar day before the local as-of date in "
            f"{COMPLETED_DAY_TIMEZONE_NAME}"
        ),
    )
    parser.add_argument(
        "--as-of-date",
        type=date.fromisoformat,
        help="deterministic local as-of date; requires --to-latest",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="retrieve a fresh official source vintage for an explicit date range",
    )
    return parser


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    if args.to_latest and args.end_date is not None:
        parser.error("--to-latest cannot be combined with --end-date")
    if args.as_of_date is not None and not args.to_latest:
        parser.error("--as-of-date requires --to-latest")
    if not args.to_latest and args.end_date is None:
        parser.error("specify --end-date or use --to-latest")
    try:
        results = ingest(
            args.cache_dir,
            args.output,
            start=args.start_date,
            end=args.end_date,
            to_latest=args.to_latest,
            as_of_date=args.as_of_date,
            force=args.force,
        )
    except ValueError as exc:
        parser.error(str(exc))
    current = resolve_current_generation(args.output)
    assert current is not None
    print(f"published_generation={current.generation}")
    for result in results:
        print(
            f"{result.station_name} ({result.climate_id}): "
            f"coverage={result.coverage_start_date}/{result.coverage_end_date}; "
            f"source_dates={result.source_dates_returned}; "
            f"artifact_rows={result.artifact_rows}; "
            f"missing_source_dates={result.missing_source_dates}; "
            f"latest_by_element={json.dumps(result.latest_available_date_by_element, sort_keys=True)}; "
            f"sha256={','.join(result.daily_source_sha256)}"
        )


if __name__ == "__main__":
    main()
