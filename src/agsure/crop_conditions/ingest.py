from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from agsure.crop_conditions import alberta, manitoba, saskatchewan
from agsure.crop_conditions.artifact import resolve_current_generation
from agsure.crop_conditions.common import (
    ReportMetadata,
    atomic_write_text,
    copy_file_fsynced,
    download_document,
    extract_pdf_text,
    finalize_generation,
    new_generation_id,
    publish_current_pointer,
    sha256_file,
    validate_observations,
    write_generation_manifest,
    write_observations_atomic,
)


DEFAULT_CACHE = Path("data/raw/crop_conditions")
DEFAULT_OUTPUT = Path("data/processed/crop_conditions.csv")
REPORTS = {
    "Alberta": {
        "adapter": alberta,
        "document_url": "https://open.alberta.ca/dataset/9af5b54d-f334-46ca-a0b1-23e560edb353/resource/116ac6d1-5e57-4c7f-9258-4378e6216081/download/agi-tedab-alberta-crop-report-2026-07-14.pdf",
        "filename": "alberta-2026-07-14.pdf",
        "publisher": "Government of Alberta, Agriculture and Irrigation",
        "program": "Alberta Crop Reporting Program",
        "title": "Alberta Crop Report: Crop conditions as of July 14, 2026",
        "release": "2026-07-17",
        "start": "",
        "end": "2026-07-14",
    },
    "Saskatchewan": {
        "adapter": saskatchewan,
        "document_url": "https://publications.saskatchewan.ca/api/v1/products/128855/formats/155587/download",
        "filename": "saskatchewan-crop-conditions-2026-07-07-to-13.pdf",
        "publisher": "Government of Saskatchewan, Ministry of Agriculture",
        "program": "Saskatchewan Crop Report",
        "title": "Saskatchewan Crop Conditions - July 7 to July 13, 2026",
        "release": "2026-07-16",
        "start": "2026-07-07",
        "end": "2026-07-13",
    },
    "Manitoba": {
        "adapter": manitoba,
        "document_url": "https://www.gov.mb.ca/agriculture/crops/seasonal-reports/crop-report/pubs/crop-report-2026-07-14.pdf",
        "filename": "manitoba-crop-report-2026-07-14.pdf",
        "publisher": "Government of Manitoba, Manitoba Agriculture",
        "program": "Manitoba Crop Report",
        "title": "Crop Report - July 14, 2026",
        "release": "2026-07-14",
        "start": "",
        "end": "",
    },
}


@dataclass(frozen=True)
class ProvinceResult:
    province: str
    observations: int
    status: str
    document_sha256: str


def _copy_cached_document(
    source_document: Path,
    source_metadata: Path,
    destination_dir: Path,
) -> tuple[Path, dict[str, str]]:
    try:
        metadata = json.loads(source_metadata.read_text(encoding="utf-8"))
        expected_digest = metadata["sha256"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f"Invalid crop-condition cache metadata: {source_metadata}") from exc
    if sha256_file(source_document) != expected_digest:
        raise ValueError(f"Cached document digest does not match {source_metadata}")
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source_document.name
    destination_metadata = destination_dir / source_metadata.name
    copy_file_fsynced(source_document, destination)
    atomic_write_text(destination_metadata, json.dumps(metadata, indent=2) + "\n")
    return destination, metadata


def _stage_document(
    province: str,
    contract: dict[str, object],
    staging_dir: Path,
    cache_dir: Path,
    previous_generation: Path | None,
    *,
    force: bool,
) -> tuple[Path, dict[str, str]]:
    province_id = province.lower()
    filename = str(contract["filename"])
    destination_dir = staging_dir / "documents" / province_id
    if not force:
        source_directories = []
        if previous_generation is not None:
            source_directories.append(previous_generation / "documents" / province_id)
        # One-time compatibility with the pre-generation cache layout.
        source_directories.append(cache_dir / province_id)
        for source_dir in source_directories:
            source_document = source_dir / filename
            source_metadata = source_dir / f"{filename}.retrieval.json"
            if source_document.is_file() and source_metadata.is_file():
                return _copy_cached_document(
                    source_document, source_metadata, destination_dir
                )
    pending = download_document(
        str(contract["document_url"]), destination_dir, filename, force=True
    )
    pending.promote()
    return pending.path, pending.metadata


def ingest(cache_dir: Path, output: Path, *, force: bool = False) -> list[ProvinceResult]:
    observations = []
    results: list[ProvinceResult] = []
    current = resolve_current_generation(output, allow_missing=True)
    previous_generation = None if current is None else current.directory
    generation = new_generation_id()
    generation_root = cache_dir / "generations"
    generation_root.mkdir(parents=True, exist_ok=True)
    staging_dir = generation_root / f".staging-{generation}"
    generation_dir = generation_root / generation
    staging_dir.mkdir()
    try:
        for province, contract in REPORTS.items():
            document_path, retrieval = _stage_document(
                province,
                contract,
                staging_dir,
                cache_dir,
                previous_generation,
                force=force,
            )
            metadata = ReportMetadata(
                publisher=contract["publisher"],
                source_program=contract["program"],
                source_report_title=contract["title"],
                source_url=contract["adapter"].SOURCE_URL,
                source_document_url=contract["document_url"],
                source_document_sha256=retrieval["sha256"],
                release_date=contract["release"],
                retrieved_at=retrieval["retrieved_at"],
                reporting_period_start=contract["start"],
                reporting_period_end=contract["end"],
                crop_year="2026",
                province=province,
            )
            parsed = contract["adapter"].parse(
                extract_pdf_text(document_path), metadata
            )
            observations.extend(parsed)
            results.append(
                ProvinceResult(
                    province=province,
                    observations=len(parsed),
                    status="implemented" if parsed else "validated; numeric series unavailable",
                    document_sha256=retrieval["sha256"],
                )
            )
        validate_observations(observations)
        generation_output = staging_dir / "processed" / output.name
        write_observations_atomic(
            generation_output,
            observations,
            manifest_data={"province_results": [result.__dict__ for result in results]},
        )
        generation_manifest_sha256 = write_generation_manifest(
            staging_dir, generation
        )
        finalize_generation(staging_dir, generation_dir)
        publish_current_pointer(
            output, generation_dir, generation, generation_manifest_sha256
        )
    except BaseException:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        raise
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest official Prairie crop reports")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    for result in ingest(args.cache_dir, args.output, force=args.force):
        print(
            f"{result.province}: {result.status}; observations={result.observations}; "
            f"sha256={result.document_sha256}"
        )


if __name__ == "__main__":
    main()
