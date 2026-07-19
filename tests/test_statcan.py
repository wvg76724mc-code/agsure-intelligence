import csv
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from agsure.statcan import (
    DownloadMetadata,
    OUTPUT_FIELDS,
    PRODUCT_ID,
    PUBLISHER,
    SOURCE_TABLE,
    SOURCE_URL,
    _parse_release_date,
    normalize_rows,
    process_archive,
)


FIXTURE = Path("tests/fixtures/statcan_32100359_small.csv")


def metadata() -> DownloadMetadata:
    return DownloadMetadata(
        publisher=PUBLISHER,
        source_table=SOURCE_TABLE,
        product_id=PRODUCT_ID,
        source_url=SOURCE_URL,
        release_date="2025-12-04",
        retrieved_at=datetime(2025, 12, 5, tzinfo=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        sha256="fixture",
        archive="fixture.zip",
    )


class StatCanIngestionTests(unittest.TestCase):
    def test_extracts_release_date_from_official_page_markup(self) -> None:
        page = "<dt>Release date:</dt><dd>2025-12-04</dd>"
        self.assertEqual(_parse_release_date(page), "2025-12-04")

    def test_filters_scope_and_preserves_provenance(self) -> None:
        with FIXTURE.open(newline="", encoding="utf-8") as handle:
            rows = list(normalize_rows(csv.DictReader(handle), metadata()))

        self.assertEqual(len(rows), 6)
        production = next(row for row in rows if row["vector"] == "v1003")
        self.assertEqual(production["commodity"], "barley")
        self.assertEqual(production["source_value"], "9.5")
        self.assertEqual(production["scalar_factor"], "thousands")
        self.assertEqual(production["value"], "9500.0")
        self.assertEqual(production["unit"], "tonnes")
        self.assertEqual(production["status_marker"], "")
        self.assertEqual(production["symbol"], "r")
        self.assertEqual(production["source_table"], "32-10-0359-01")
        self.assertEqual(production["coordinate"], "1.1.3")

    def test_converts_yield_to_tonnes_per_hectare(self) -> None:
        with FIXTURE.open(newline="", encoding="utf-8") as handle:
            rows = list(normalize_rows(csv.DictReader(handle), metadata()))
        item = next(row for row in rows if row["metric"] == "yield")
        self.assertEqual(item["source_value"], "3500")
        self.assertEqual(item["source_unit"], "Kilograms per hectare")
        self.assertEqual(item["value"], "3.500")
        self.assertEqual(item["unit"], "tonnes per hectare")

    def test_retains_missing_observation_without_repairing_it(self) -> None:
        with FIXTURE.open(newline="", encoding="utf-8") as handle:
            rows = list(normalize_rows(csv.DictReader(handle), metadata()))
        item = next(row for row in rows if row["vector"] == "v1004")
        self.assertEqual(item["commodity"], "dry-peas")
        self.assertEqual(item["source_value"], "")
        self.assertEqual(item["value"], "")
        self.assertEqual(item["status_marker"], "..")
        self.assertEqual(item["symbol"], "")
        self.assertEqual(item["observation_status"], "estimated")

    def test_processes_local_zip_without_network(self) -> None:
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "fixture.zip"
            output = Path(directory) / "processed.csv"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.write(FIXTURE, "32100359.csv")
            count = process_archive(archive, output, metadata())
            with output.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)

        self.assertEqual(count, 6)
        self.assertEqual(tuple(reader.fieldnames or ()), OUTPUT_FIELDS)
        self.assertEqual(len(rows), 6)

    def test_rejects_unknown_scalar_factor_in_selected_row(self) -> None:
        row = {
            "REF_DATE": "2025",
            "GEO": "Canada",
            "DGUID": "d",
            "Type of crop": "Barley",
            "Harvest disposition": "Production (metric tonnes)",
            "UOM": "Metric tonnes",
            "SCALAR_FACTOR": "quadrillions",
            "VECTOR": "v1",
            "COORDINATE": "1.1.1",
            "VALUE": "2",
            "STATUS": "",
            "SYMBOL": "",
            "TERMINATED": "",
            "DECIMALS": "0",
        }
        with self.assertRaisesRegex(ValueError, "Unsupported scalar factor"):
            list(normalize_rows([row], metadata()))


if __name__ == "__main__":
    unittest.main()
