from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agsure.analysis import calculate_supply_pressure
from agsure.crop_conditions import alberta, ingest as crop_ingest, manitoba, saskatchewan
from agsure.crop_conditions.artifact import (
    compare_selected_period,
    read_artifact,
    resolve_current_generation,
    select_series,
)
from agsure.crop_conditions.common import (
    ReportMetadata,
    atomic_write_text,
    current_pointer_path,
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
from agsure.io import load_observations


FIXTURES = Path("tests/fixtures/crop_conditions")


def metadata(province: str) -> ReportMetadata:
    values = {
        "Alberta": (alberta, "Alberta Crop Report: Crop conditions as of July 14, 2026", "2026-07-17", "", "2026-07-14"),
        "Saskatchewan": (saskatchewan, "Saskatchewan Crop Conditions - July 7 to July 13, 2026", "2026-07-16", "2026-07-07", "2026-07-13"),
        "Manitoba": (manitoba, "Crop Report - July 14, 2026", "2026-07-14", "", ""),
    }
    adapter, title, release, start, end = values[province]
    return ReportMetadata(
        publisher=f"Synthetic {province} fixture publisher",
        source_program=f"{province} Crop Report",
        source_report_title=title,
        source_url=adapter.SOURCE_URL,
        source_document_url=f"https://example.invalid/{province.lower()}.pdf",
        source_document_sha256="0" * 64,
        release_date=release,
        retrieved_at="2026-07-19T12:00:00Z",
        reporting_period_start=start,
        reporting_period_end=end,
        crop_year="2026",
        province=province,
    )


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def synthetic_pdf_bytes(text: str = "Synthetic crop report") -> bytes:
    """Return a tiny synthetic PDF with embedded text and no government content."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
        + stream + b"\nendstream",
    )
    content = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(content))
        content.extend(f"{number} 0 obj\n".encode("ascii") + obj + b"\nendobj\n")
    xref = len(content)
    content.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    content.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    content.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    return bytes(content)


def publish_test_generation(
    output: Path,
    rows: list,
    *,
    cache_dir: Path | None = None,
    document_prefix: str = "synthetic",
):
    cache_dir = cache_dir or output.parent / "crop-condition-cache"
    generation = new_generation_id()
    generation_root = cache_dir / "generations"
    generation_root.mkdir(parents=True, exist_ok=True)
    staging = generation_root / f".staging-{generation}"
    final = generation_root / generation
    staging.mkdir()
    for province in ("alberta", "saskatchewan", "manitoba"):
        document_dir = staging / "documents" / province
        document_dir.mkdir(parents=True)
        document = document_dir / f"{province}.pdf"
        payload = f"{document_prefix}-{province}".encode()
        document.write_bytes(payload)
        atomic_write_text(
            document.with_name(f"{document.name}.retrieval.json"),
            json.dumps(
                {
                    "source_url": f"https://example.invalid/{province}.pdf",
                    "retrieved_at": "2026-07-19T12:00:00Z",
                    "sha256": hashlib.sha256(payload).hexdigest(),
                },
                indent=2,
            )
            + "\n",
        )
    write_observations_atomic(staging / "processed" / output.name, rows)
    manifest_digest = write_generation_manifest(staging, generation)
    finalize_generation(staging, final)
    publish_current_pointer(output, final, generation, manifest_digest)
    resolved = resolve_current_generation(output)
    assert resolved is not None
    return resolved


class AlbertaParserTests(unittest.TestCase):
    def test_exact_crop_region_measure_unit_period_and_provenance(self) -> None:
        rows = alberta.parse(fixture("alberta_2026_synthetic.txt"), metadata("Alberta"))
        validate_observations(rows)
        self.assertEqual(len(rows), 30)
        barley = next(
            row for row in rows
            if row.source_crop == "Barley" and row.source_region == "South"
        )
        self.assertEqual(barley.commodity, "barley")
        self.assertEqual(barley.source_measure, "Per Cent Rated Good-to-Excellent Conditions")
        self.assertEqual(barley.category, "good-to-excellent")
        self.assertEqual((barley.source_value, barley.value, barley.unit), ("83.8%", "83.8", "percent"))
        self.assertEqual(barley.reporting_period_end, "2026-07-14")
        self.assertEqual((barley.source_page, barley.source_table), ("1", "Table 1: Regional Crop Condition Ratings"))

    def test_unavailable_exact_region_is_not_filled(self) -> None:
        rows = alberta.parse(fixture("alberta_2026_synthetic.txt"), metadata("Alberta"))
        durum_peace = next(
            row for row in rows
            if row.source_crop == "Durum" and row.source_region == "Peace"
        )
        self.assertEqual(durum_peace.source_value, "-")
        self.assertEqual(durum_peace.value, "")
        self.assertEqual(durum_peace.observation_status, "unavailable")

    def test_missing_table_and_aggregate_crop_fail_closed(self) -> None:
        text = fixture("alberta_2026_synthetic.txt")
        with self.assertRaisesRegex(ValueError, "Alberta parser failed.*Table 1"):
            alberta.parse(text.replace("Table 1:", "Table X:"), metadata("Alberta"))
        with self.assertRaisesRegex(ValueError, "exact crop rows"):
            alberta.parse(text.replace("Spring Wheat", "All Wheat"), metadata("Alberta"))


class SaskatchewanParserTests(unittest.TestCase):
    def test_all_regions_crops_categories_and_field_pea_terminology(self) -> None:
        rows = saskatchewan.parse(
            fixture("saskatchewan_2026_synthetic.txt"), metadata("Saskatchewan")
        )
        validate_observations(rows)
        self.assertEqual(len(rows), 7 * 5 * 5)
        self.assertEqual({row.source_region for row in rows}, {item[0] for item in saskatchewan.REGIONS})
        peas = next(row for row in rows if row.source_crop == "Field Pea")
        self.assertEqual(peas.commodity, "field-peas")
        self.assertEqual(peas.source_crop, "Field Pea")
        self.assertEqual(peas.source_measure, "Crop Conditions")
        self.assertEqual(peas.extraction_method, "embedded_pdf_text")

    def test_source_drift_malformed_table_and_unexpected_category_fail(self) -> None:
        text = fixture("saskatchewan_2026_synthetic.txt")
        with self.assertRaisesRegex(ValueError, "seven regional"):
            saskatchewan.parse(text.replace(saskatchewan.PRIMARY_HEADER, "changed", 1), metadata("Saskatchewan"))
        with self.assertRaisesRegex(ValueError, "eight primary"):
            saskatchewan.parse(text.replace("20% 20% 20% 20% 20% 20% 20% 20%", "20% 20%", 1), metadata("Saskatchewan"))
        with self.assertRaisesRegex(ValueError, "eight primary"):
            saskatchewan.parse(text.replace("excellent", "great", 1), metadata("Saskatchewan"))


class ManitobaParserTests(unittest.TestCase):
    def test_validated_narrative_report_emits_no_inferred_numbers(self) -> None:
        rows = manitoba.parse(
            fixture("manitoba_2026_synthetic.txt"), metadata("Manitoba")
        )
        self.assertEqual(rows, [])

    def test_missing_reporting_region_fails_closed(self) -> None:
        text = fixture("manitoba_2026_synthetic.txt").replace("Interlake", "Area Five")
        with self.assertRaisesRegex(ValueError, "Manitoba parser failed.*Interlake"):
            manitoba.parse(text, metadata("Manitoba"))


class CropConditionValidationTests(unittest.TestCase):
    def test_extract_pdf_text_reads_small_synthetic_embedded_text_pdf(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.pdf"
            path.write_bytes(synthetic_pdf_bytes())
            self.assertIn("Synthetic crop report", extract_pdf_text(path))

    def test_category_total_rounding_tolerance(self) -> None:
        rows = saskatchewan.parse(
            fixture("saskatchewan_2026_synthetic.txt"), metadata("Saskatchewan")
        )
        changed = list(rows)
        changed[0] = replace(changed[0], source_value="20.8%", value="20.8")
        validate_observations(changed, rounding_tolerance=Decimal("1"))
        changed[0] = replace(changed[0], source_value="22%", value="22")
        with self.assertRaisesRegex(ValueError, "categories total"):
            validate_observations(changed, rounding_tolerance=Decimal("1"))

    def test_duplicate_key_and_cross_province_region_fail(self) -> None:
        rows = alberta.parse(fixture("alberta_2026_synthetic.txt"), metadata("Alberta"))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            validate_observations([*rows, rows[0]])
        crossed = [replace(rows[0], source_region="South East", source_region_id="south-east"), *rows[1:]]
        with self.assertRaisesRegex(ValueError, "not valid for Alberta"):
            validate_observations(crossed)

    def test_region_label_and_identifier_pair_must_match_in_every_province(self) -> None:
        base = alberta.parse(fixture("alberta_2026_synthetic.txt"), metadata("Alberta"))[0]
        cases = (
            ("Alberta", "Central", "south"),
            ("Saskatchewan", "South West", "south-east"),
            ("Manitoba", "Northwest", "southwest"),
        )
        for province, wrong_label, valid_id in cases:
            with self.subTest(province=province):
                row = replace(
                    base, province=province, source_region=wrong_label,
                    source_region_id=valid_id,
                )
                with self.assertRaisesRegex(ValueError, f"not valid for {province}"):
                    validate_observations([row])

    def test_category_totals_never_combine_different_source_measures(self) -> None:
        rows = saskatchewan.parse(
            fixture("saskatchewan_2026_synthetic.txt"), metadata("Saskatchewan")
        )
        distribution = [
            row for row in rows
            if row.source_region_id == "provincial" and row.source_crop == "Barley"
        ]
        split = [
            replace(row, source_measure="Condition Scale A" if index < 2 else "Condition Scale B")
            for index, row in enumerate(distribution)
        ]
        with self.assertRaisesRegex(ValueError, "Unexpected crop-condition categories"):
            validate_observations(split)

    def test_artifact_history_uses_exact_identity_only(self) -> None:
        rows = alberta.parse(fixture("alberta_2026_synthetic.txt"), metadata("Alberta"))
        with TemporaryDirectory() as directory:
            path = Path(directory) / "crop_conditions.csv"
            publish_test_generation(path, rows)
            loaded = read_artifact(path)
        series = select_series(
            loaded,
            province="Alberta",
            source_region_id="south",
            commodity="barley",
            observation_type="crop-condition",
            source_measure="Per Cent Rated Good-to-Excellent Conditions",
            category="good-to-excellent",
        )
        self.assertTrue(series.available)
        self.assertEqual(series.latest["value"], "83.8")

    def test_previous_value_is_relative_to_selected_middle_period(self) -> None:
        rows = alberta.parse(fixture("alberta_2026_synthetic.txt"), metadata("Alberta"))
        current = next(
            row for row in rows
            if row.source_region_id == "south" and row.commodity == "barley"
        )
        oldest = replace(
            current,
            source_value="75.0%", value="75.0",
            reporting_period_end="2026-06-30", release_date="2026-07-03",
        )
        middle = replace(
            current,
            source_value="80.0%", value="80.0",
            reporting_period_end="2026-07-07", release_date="2026-07-10",
        )
        series = select_series(
            [oldest.as_row(), middle.as_row(), current.as_row()],
            province="Alberta",
            source_region_id="south",
            commodity="barley",
            observation_type="crop-condition",
            source_measure="Per Cent Rated Good-to-Excellent Conditions",
            category="good-to-excellent",
        )
        comparison = compare_selected_period(series.rows, "2026-07-07")
        self.assertEqual(comparison.selected["value"], "80.0")
        self.assertEqual(comparison.previous["value"], "75.0")
        self.assertEqual(comparison.change_percentage_points, Decimal("5.0"))

    def test_previous_value_requires_every_exact_comparison_identity(self) -> None:
        rows = alberta.parse(fixture("alberta_2026_synthetic.txt"), metadata("Alberta"))
        current = next(
            row for row in rows
            if row.source_region_id == "south" and row.commodity == "barley"
        ).as_row()
        prior = {
            **current,
            "value": "80.0",
            "source_value": "80.0%",
            "reporting_period_end": "2026-07-07",
        }
        mismatches = {
            "province": "Saskatchewan",
            "source_region": "Central",
            "source_region_id": "central",
            "commodity": "canola",
            "observation_type": "crop-development",
            "source_measure": "Different measure",
            "category": "different-category",
            "unit": "different-unit",
            "baseline_type": "five-year-average",
            "baseline_period": "2021-2025",
            "source_program": "Different crop report",
        }
        for field, value in mismatches.items():
            with self.subTest(field=field):
                changed_prior = {**prior, field: value}
                comparison = compare_selected_period(
                    [changed_prior, current], "2026-07-14"
                )
                self.assertIsNone(comparison.previous)
                self.assertIsNone(comparison.change_percentage_points)

    def test_artifact_reader_rejects_interrupted_mismatched_generation(self) -> None:
        rows = alberta.parse(fixture("alberta_2026_synthetic.txt"), metadata("Alberta"))
        with TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / "crop_conditions.csv"
            generation = publish_test_generation(current, rows)
            changed = [replace(rows[0], source_value="82.8%", value="82.8"), *rows[1:]]
            replacement = root / "replacement.csv"
            write_observations_atomic(replacement, changed)
            generation.artifact.write_bytes(replacement.read_bytes())
            with self.assertRaisesRegex(ValueError, "generation file is mismatched"):
                read_artifact(current)

    def test_forced_malformed_download_preserves_valid_cache_and_metadata(self) -> None:
        from pypdf.errors import PdfReadError

        with TemporaryDirectory() as directory:
            cache = Path(directory)
            destination = cache / "report.pdf"
            metadata_path = cache / "report.pdf.retrieval.json"
            valid_pdf = synthetic_pdf_bytes("Previously valid report")
            destination.write_bytes(valid_pdf)
            prior_metadata = {
                "source_url": "https://example.invalid/report.pdf",
                "retrieved_at": "2026-07-01T00:00:00Z",
                "sha256": hashlib.sha256(valid_pdf).hexdigest(),
            }
            metadata_text = json.dumps(prior_metadata, indent=2) + "\n"
            metadata_path.write_text(metadata_text, encoding="utf-8")
            with patch("urllib.request.urlopen", return_value=io.BytesIO(b"not a pdf")):
                pending = download_document(
                    prior_metadata["source_url"], cache, "report.pdf", force=True
                )
            with self.assertRaises(PdfReadError):
                extract_pdf_text(pending.path)
            pending.discard()
            self.assertEqual(destination.read_bytes(), valid_pdf)
            self.assertEqual(metadata_path.read_text(encoding="utf-8"), metadata_text)
            cached = download_document(
                prior_metadata["source_url"], cache, "report.pdf", force=False
            )
            self.assertFalse(cached.pending)
            self.assertIn("Previously valid report", extract_pdf_text(cached.path))

    def test_refuses_empty_overwrite(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "no observations"):
                write_observations_atomic(Path(directory) / "empty.csv", [])

    def test_official_crop_conditions_never_enter_synthetic_score(self) -> None:
        official_rows = alberta.parse(
            fixture("alberta_2026_synthetic.txt"), metadata("Alberta")
        )
        self.assertTrue(official_rows)
        synthetic = [
            row for row in load_observations("sample_data/crops_synthetic.csv")
            if row.commodity == "barley"
        ]
        self.assertEqual(calculate_supply_pressure(synthetic).score, Decimal("72.1"))


class GenerationPublicationTests(unittest.TestCase):
    def _run_ingest(
        self,
        cache_dir: Path,
        output: Path,
        prefix: str,
        *,
        alberta_text: str | None = None,
        urlopen_side_effect=None,
    ):
        payloads = [
            io.BytesIO(f"{prefix}-{province}".encode())
            for province in ("alberta", "saskatchewan", "manitoba")
        ]
        texts = [
            alberta_text or fixture("alberta_2026_synthetic.txt"),
            fixture("saskatchewan_2026_synthetic.txt"),
            fixture("manitoba_2026_synthetic.txt"),
        ]
        with (
            patch(
                "urllib.request.urlopen",
                side_effect=payloads if urlopen_side_effect is None else urlopen_side_effect,
            ),
            patch.object(crop_ingest, "extract_pdf_text", side_effect=texts),
        ):
            return crop_ingest.ingest(cache_dir, output, force=True)

    def test_failure_before_current_swap_leaves_previous_generation_readable(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            output = root / "processed" / "crop_conditions.csv"
            self._run_ingest(cache, output, "first")
            previous = resolve_current_generation(output)
            previous_rows = read_artifact(output)
            pointer_bytes = current_pointer_path(output).read_bytes()
            with patch.object(
                crop_ingest,
                "publish_current_pointer",
                side_effect=RuntimeError("interrupted before CURRENT swap"),
            ):
                with self.assertRaisesRegex(RuntimeError, "before CURRENT"):
                    self._run_ingest(cache, output, "second")
            current = resolve_current_generation(output)
            self.assertEqual(current.generation, previous.generation)
            self.assertEqual(read_artifact(output), previous_rows)
            self.assertEqual(current_pointer_path(output).read_bytes(), pointer_bytes)
            self.assertTrue(previous.directory.is_dir())

    def test_interruption_staging_one_province_preserves_all_prior_files(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            output = root / "processed" / "crop_conditions.csv"
            self._run_ingest(cache, output, "first")
            previous = resolve_current_generation(output)
            previous_files = {
                item.relative_to(previous.directory).as_posix(): item.read_bytes()
                for item in previous.directory.rglob("*")
                if item.is_file()
            }
            previous_rows = read_artifact(output)
            interrupted_downloads = [
                io.BytesIO(b"second-alberta"),
                OSError("interrupted while staging Saskatchewan"),
            ]
            with self.assertRaisesRegex(OSError, "staging Saskatchewan"):
                self._run_ingest(
                    cache,
                    output,
                    "second",
                    urlopen_side_effect=interrupted_downloads,
                )
            current = resolve_current_generation(output)
            current_files = {
                item.relative_to(current.directory).as_posix(): item.read_bytes()
                for item in current.directory.rglob("*")
                if item.is_file()
            }
            self.assertEqual(current.generation, previous.generation)
            self.assertEqual(current_files, previous_files)
            self.assertEqual(read_artifact(output), previous_rows)

    def test_current_never_exposes_a_partial_generation(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "processed" / "crop_conditions.csv"
            generation = "1" * 32
            partial = root / "cache" / "generations" / generation
            partial.mkdir(parents=True)
            (partial / "only-one-file.pdf").write_bytes(b"partial")
            pointer = {
                "publication_version": 1,
                "generation": generation,
                "generation_path": Path(
                    os.path.relpath(partial, output.parent)
                ).as_posix(),
                "generation_manifest_sha256": "0" * 64,
            }
            atomic_write_text(
                current_pointer_path(output), json.dumps(pointer, indent=2) + "\n"
            )
            with self.assertRaisesRegex(ValueError, "manifest is mismatched"):
                read_artifact(output)

    def test_corrupt_or_nonexistent_current_target_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "processed" / "crop_conditions.csv"
            pointer_path = current_pointer_path(output)
            atomic_write_text(pointer_path, "not-json\n")
            with self.assertRaisesRegex(ValueError, "CURRENT pointer is malformed"):
                read_artifact(output)
            generation = "2" * 32
            pointer = {
                "publication_version": 1,
                "generation": generation,
                "generation_path": f"../cache/generations/{generation}",
                "generation_manifest_sha256": "0" * 64,
            }
            atomic_write_text(pointer_path, json.dumps(pointer, indent=2) + "\n")
            with self.assertRaisesRegex(ValueError, "target does not exist"):
                read_artifact(output)

    def test_success_switches_documents_metadata_and_artifact_together(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            output = root / "processed" / "crop_conditions.csv"
            self._run_ingest(cache, output, "first")
            previous = resolve_current_generation(output)
            changed_alberta = fixture("alberta_2026_synthetic.txt").replace(
                "83.8%", "82.8%", 1
            )
            self._run_ingest(
                cache, output, "second", alberta_text=changed_alberta
            )
            current = resolve_current_generation(output)
            self.assertNotEqual(current.generation, previous.generation)
            self.assertTrue(previous.directory.is_dir())
            for province, contract in crop_ingest.REPORTS.items():
                province_id = province.lower()
                document = (
                    current.directory / "documents" / province_id / contract["filename"]
                )
                metadata_path = document.with_name(
                    f"{document.name}.retrieval.json"
                )
                self.assertEqual(document.read_bytes(), f"second-{province_id}".encode())
                retrieval = json.loads(metadata_path.read_text(encoding="utf-8"))
                self.assertEqual(retrieval["sha256"], sha256_file(document))
            rows = read_artifact(output)
            south_barley = next(
                row for row in rows
                if row["province"] == "Alberta"
                and row["source_region_id"] == "south"
                and row["commodity"] == "barley"
            )
            self.assertEqual(south_barley["value"], "82.8")
            processed_manifest = json.loads(
                current.artifact_manifest.read_text(encoding="utf-8")
            )
            self.assertEqual(
                processed_manifest["artifact_sha256"], sha256_file(current.artifact)
            )


class CropConditionDashboardTests(unittest.TestCase):
    def _write_artifact(self, root: Path) -> None:
        alberta_rows = alberta.parse(
            fixture("alberta_2026_synthetic.txt"), metadata("Alberta")
        )
        current = next(
            row for row in alberta_rows
            if row.source_region_id == "south" and row.commodity == "barley"
        )
        history = [
            replace(
                current, source_value="75.0%", value="75.0",
                reporting_period_end="2026-06-30", release_date="2026-07-03",
            ),
            replace(
                current, source_value="80.0%", value="80.0",
                reporting_period_end="2026-07-07", release_date="2026-07-10",
            ),
        ]
        rows = alberta_rows + history + saskatchewan.parse(
            fixture("saskatchewan_2026_synthetic.txt"), metadata("Saskatchewan")
        )
        publish_test_generation(root / "crop_conditions.csv", rows)

    def test_detailed_view_all_provinces_and_commodities(self) -> None:
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError as exc:  # pragma: no cover
            self.fail(f"Streamlit dashboard dependency is unavailable: {exc}")
        import os

        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_artifact(root)
            previous = os.environ.get("AGSURE_PROCESSED_DIR")
            os.environ["AGSURE_PROCESSED_DIR"] = str(root)
            try:
                identities = {
                    "Alberta": ("barley", "canola", "spring-wheat", "durum-wheat", "dry-peas"),
                    "Saskatchewan": (
                        "barley", "canola", "spring-wheat", "durum-wheat", "field-peas",
                    ),
                    "Manitoba": (
                        "barley", "canola", "spring-wheat", "durum-wheat", "dry-peas",
                    ),
                }
                for province, commodities in identities.items():
                    for commodity in commodities:
                        with self.subTest(province=province, commodity=commodity):
                            app = AppTest.from_file("src/agsure/dashboard.py").run(timeout=30)
                            app.selectbox[0].set_value("crop-conditions").run(timeout=30)
                            app.selectbox(key="regional_province").set_value(province).run(timeout=30)
                            app.selectbox(key=f"regional_commodity_{province}").set_value(
                                commodity
                            ).run(timeout=30)
                            self.assertEqual(list(app.exception), [])
                            if province == "Manitoba":
                                self.assertTrue(
                                    any("Not available" in item.value for item in app.warning)
                                )
            finally:
                if previous is None:
                    os.environ.pop("AGSURE_PROCESSED_DIR", None)
                else:
                    os.environ["AGSURE_PROCESSED_DIR"] = previous

    def test_middle_reporting_period_uses_its_own_previous_week(self) -> None:
        from streamlit.testing.v1 import AppTest
        import os

        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_artifact(root)
            previous = os.environ.get("AGSURE_PROCESSED_DIR")
            os.environ["AGSURE_PROCESSED_DIR"] = str(root)
            try:
                app = AppTest.from_file("src/agsure/dashboard.py").run(timeout=30)
                app.selectbox[0].set_value("crop-conditions").run(timeout=30)
                app.selectbox(key="regional_region_Alberta").set_value("south").run(timeout=30)
                period_key = (
                    "regional_reporting_period_Alberta_south_barley_crop-condition_"
                    "Per Cent Rated Good-to-Excellent Conditions_good-to-excellent"
                )
                app.selectbox(key=period_key).set_value("2026-07-07").run(timeout=30)
                metrics = {item.label: item.value for item in app.metric}
                self.assertEqual(metrics["Selected official observation"], "80.0%")
                self.assertEqual(metrics["Previous comparable report"], "75.0%")
                self.assertEqual(metrics["Change"], "+5.0 pp")
                self.assertEqual(list(app.exception), [])
            finally:
                if previous is None:
                    os.environ.pop("AGSURE_PROCESSED_DIR", None)
                else:
                    os.environ["AGSURE_PROCESSED_DIR"] = previous

    def test_selector_state_resets_across_province_region_and_crop_changes(self) -> None:
        from streamlit.testing.v1 import AppTest
        import os

        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_artifact(root)
            previous = os.environ.get("AGSURE_PROCESSED_DIR")
            os.environ["AGSURE_PROCESSED_DIR"] = str(root)
            try:
                app = AppTest.from_file("src/agsure/dashboard.py").run(timeout=30)
                app.selectbox[0].set_value("crop-conditions").run(timeout=30)
                app.selectbox(key="regional_region_Alberta").set_value("peace").run(timeout=30)
                app.selectbox(key="regional_commodity_Alberta").set_value("dry-peas").run(
                    timeout=30
                )
                app.selectbox(key="regional_province").set_value("Saskatchewan").run(
                    timeout=30
                )
                self.assertNotIn(
                    "dry-peas", app.selectbox(key="regional_commodity_Saskatchewan").options
                )
                app.selectbox(key="regional_region_Saskatchewan").set_value(
                    "north-west"
                ).run(timeout=30)
                app.selectbox(key="regional_commodity_Saskatchewan").set_value(
                    "field-peas"
                ).run(timeout=30)
                category_key = (
                    "regional_category_Saskatchewan_north-west_field-peas_"
                    "crop-condition_Crop Conditions"
                )
                app.selectbox(key=category_key).set_value("poor").run(timeout=30)
                self.assertEqual(list(app.exception), [])
                self.assertTrue(
                    any("not treated as equivalent" in item.value for item in app.caption)
                )
            finally:
                if previous is None:
                    os.environ.pop("AGSURE_PROCESSED_DIR", None)
                else:
                    os.environ["AGSURE_PROCESSED_DIR"] = previous

    def test_unified_requires_province_and_region_before_display(self) -> None:
        from streamlit.testing.v1 import AppTest
        import os

        with TemporaryDirectory() as directory:
            root = Path(directory)
            names = {
                "unified_production.csv": "statcan_crop_production.csv",
                "unified_stocks.csv": "statcan_crop_stocks.csv",
                "unified_supply.csv": "statcan_supply_disposition.csv",
                "unified_stocks_to_use.csv": "statcan_stocks_to_use.csv",
            }
            for source, destination in names.items():
                shutil.copy(Path("tests/fixtures") / source, root / destination)
            self._write_artifact(root)
            previous = os.environ.get("AGSURE_PROCESSED_DIR")
            os.environ["AGSURE_PROCESSED_DIR"] = str(root)
            try:
                app = AppTest.from_file("src/agsure/dashboard.py").run(timeout=30)
                self.assertIsNone(app.selectbox(key="unified_regional_province").value)
                self.assertTrue(
                    any("Select a province" in item.value for item in app.info)
                )
                app.selectbox(key="unified_regional_province").set_value("Alberta").run(timeout=30)
                self.assertIsNone(app.selectbox(key="unified_regional_region_Alberta").value)
                app.selectbox(key="unified_regional_region_Alberta").set_value(
                    "south"
                ).run(timeout=30)
                self.assertEqual(list(app.exception), [])
                self.assertTrue(
                    any("Regional systems" in item.value for item in app.warning)
                )
            finally:
                if previous is None:
                    os.environ.pop("AGSURE_PROCESSED_DIR", None)
                else:
                    os.environ["AGSURE_PROCESSED_DIR"] = previous


if __name__ == "__main__":
    unittest.main()
