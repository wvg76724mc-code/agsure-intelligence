import csv
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from agsure.statcan import DownloadMetadata
from agsure.statcan_supply_disposition import (
    MEASURES,
    OUTPUT_FIELDS,
    PRODUCT_ID,
    PUBLISHER,
    SOURCE_TABLE,
    SOURCE_URL,
    normalize_rows,
    process_archive,
)


FIXTURE = Path("tests/fixtures/statcan_32100013_small.csv")


def metadata() -> DownloadMetadata:
    return DownloadMetadata(
        publisher=PUBLISHER,
        source_table=SOURCE_TABLE,
        product_id=PRODUCT_ID,
        source_url=SOURCE_URL,
        release_date="2026-05-06",
        retrieved_at=datetime(2026, 7, 19, tzinfo=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        sha256="fixture",
        archive="fixture.zip",
    )


def fixture_rows() -> list[dict[str, str]]:
    with FIXTURE.open(newline="", encoding="utf-8") as handle:
        return list(normalize_rows(csv.DictReader(handle), metadata()))


class StatCanSupplyDispositionIngestionTests(unittest.TestCase):
    def test_retains_all_exact_measure_labels_and_provenance(self) -> None:
        rows = fixture_rows()

        self.assertEqual({row["measure"] for row in rows}, set(MEASURES))
        item = next(row for row in rows if row["vector"] == "v3016")
        self.assertEqual(item["measure"], "Animal feed, waste and dockage")
        self.assertEqual(item["original_value"], "3935")
        self.assertEqual(item["original_unit"], "Metric tonnes")
        self.assertEqual(item["uom_id"], "214")
        self.assertEqual(item["scalar_factor"], "thousands")
        self.assertEqual(item["scalar_id"], "3")
        self.assertEqual(item["normalized_tonnes"], "3935000")
        self.assertEqual(item["source_table"], "32-10-0013-01")
        self.assertEqual(item["source_note_ids"], "1;2;5;9;12;23;24;25;26")
        self.assertEqual(item["coordinate"], "1.5.16")
        self.assertEqual(item["observation_status"], "official")

    def test_derives_crop_year_and_cumulative_reporting_period(self) -> None:
        rows = fixture_rows()
        march = next(row for row in rows if row["vector"] == "v3001")
        july = next(row for row in rows if row["vector"] == "v3021")
        december = next(row for row in rows if row["vector"] == "v3022")

        self.assertEqual(march["snapshot_period"], "March")
        self.assertEqual(march["crop_year"], "2024/2025")
        self.assertEqual(march["reporting_period_start"], "2024-08")
        self.assertEqual(march["reporting_period_end"], "2025-03")
        self.assertEqual(july["crop_year"], "2024/2025")
        self.assertEqual(december["crop_year"], "2025/2026")
        self.assertEqual(december["reporting_period_start"], "2025-08")
        self.assertEqual(
            december["reporting_period_basis"], "Cumulative over the crop year"
        )

    def test_does_not_map_aggregate_wheat_members_to_spring_wheat(self) -> None:
        rows = fixture_rows()
        self.assertNotIn("spring-wheat", {row["commodity"] for row in rows})
        self.assertNotIn("v3998", {row["vector"] for row in rows})
        self.assertNotIn("v3999", {row["vector"] for row in rows})

    def test_keeps_unavailable_value_blank_and_traceable(self) -> None:
        item = next(row for row in fixture_rows() if row["vector"] == "v3023")

        self.assertEqual(item["original_value"], "")
        self.assertEqual(item["normalized_tonnes"], "")
        self.assertEqual(item["status_marker"], "..")
        self.assertEqual(item["observation_status"], "unavailable")

    def test_keeps_confidential_and_missing_values_blank(self) -> None:
        rows = fixture_rows()
        confidential = next(row for row in rows if row["vector"] == "v3024")
        missing = next(row for row in rows if row["vector"] == "v3025")

        self.assertEqual(confidential["normalized_tonnes"], "")
        self.assertEqual(confidential["status_marker"], "x")
        self.assertEqual(confidential["observation_status"], "confidential")
        self.assertEqual(missing["original_value"], "")
        self.assertEqual(missing["normalized_tonnes"], "")
        self.assertEqual(missing["observation_status"], "missing")

    def test_preserves_revision_marker_without_changing_value(self) -> None:
        item = next(row for row in fixture_rows() if row["vector"] == "v3021")

        self.assertEqual(item["symbol"], "r")
        self.assertEqual(item["revision_marker"], "r")
        self.assertEqual(item["normalized_tonnes"], "1500000")

    def test_processes_local_zip_without_network(self) -> None:
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "fixture.zip"
            output = Path(directory) / "processed.csv"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.write(FIXTURE, "32100013.csv")
            count = process_archive(archive, output, metadata())
            with output.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)

        self.assertEqual(count, 25)
        self.assertEqual(tuple(reader.fieldnames or ()), OUTPUT_FIELDS)
        self.assertEqual(len(rows), 25)


if __name__ == "__main__":
    unittest.main()
