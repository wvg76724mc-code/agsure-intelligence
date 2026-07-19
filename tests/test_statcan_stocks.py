import csv
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from agsure.statcan import DownloadMetadata
from agsure.statcan_stocks import (
    OUTPUT_FIELDS,
    PRODUCT_ID,
    PUBLISHER,
    SOURCE_TABLE,
    SOURCE_URL,
    normalize_rows,
    process_archive,
)
from agsure.stocks import compare_same_snapshot


FIXTURE = Path("tests/fixtures/statcan_32100007_small.csv")


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


class StatCanStocksIngestionTests(unittest.TestCase):
    def test_filters_exact_scope_and_preserves_provenance(self) -> None:
        rows = fixture_rows()

        self.assertEqual(len(rows), 13)
        item = next(row for row in rows if row["vector"] == "v2102")
        self.assertEqual(item["commodity"], "durum-wheat")
        self.assertEqual(item["source_crop"], "Wheat, durum")
        self.assertEqual(item["stock_type"], "Commercial stocks")
        self.assertEqual(item["original_value"], "931")
        self.assertEqual(item["original_unit"], "Metric tonnes")
        self.assertEqual(item["scalar_factor"], "thousands")
        self.assertEqual(item["normalized_tonnes"], "931000")
        self.assertEqual(item["reference_date"], "2026-03-31")
        self.assertEqual(item["snapshot_period"], "March 31")
        self.assertEqual(item["source_table"], "32-10-0007-01")
        self.assertEqual(item["coordinate"], "1.3.2")

    def test_does_not_map_wheat_excluding_durum_to_spring_wheat(self) -> None:
        rows = fixture_rows()
        self.assertNotIn("spring-wheat", {row["commodity"] for row in rows})
        self.assertNotIn("v2998", {row["vector"] for row in rows})

    def test_retains_unpublished_rows_as_blank_and_traceable(self) -> None:
        rows = fixture_rows()
        confidential = next(row for row in rows if row["vector"] == "v2104")
        unavailable = next(row for row in rows if row["vector"] == "v2105")

        self.assertEqual(confidential["normalized_tonnes"], "")
        self.assertEqual(confidential["status_marker"], "x")
        self.assertEqual(unavailable["normalized_tonnes"], "")
        self.assertEqual(unavailable["status_marker"], "..")
        self.assertEqual(unavailable["observation_status"], "modelled")

    def test_distinguishes_published_modelled_farm_stock_methods(self) -> None:
        rows = fixture_rows()
        july_farm_stocks = next(row for row in rows if row["vector"] == "v2106")
        march_total = next(row for row in rows if row["vector"] == "v2006")

        self.assertEqual(july_farm_stocks["observation_status"], "modelled")
        self.assertEqual(march_total["observation_status"], "estimated")

    def test_processes_local_zip_without_network(self) -> None:
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "fixture.zip"
            output = Path(directory) / "processed.csv"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.write(FIXTURE, "32100007.csv")
            count = process_archive(archive, output, metadata())
            with output.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)

        self.assertEqual(count, 13)
        self.assertEqual(tuple(reader.fieldnames or ()), OUTPUT_FIELDS)
        self.assertEqual(len(rows), 13)


class StockComparisonTests(unittest.TestCase):
    def test_compares_only_the_same_snapshot_across_consecutive_years(self) -> None:
        observations = {
            f"{year}-03": Decimal(str(value))
            for year, value in zip(
                range(2020, 2027), (100, 110, 120, 130, 140, 150, 180)
            )
        }
        result = compare_same_snapshot(observations)

        self.assertEqual(result.reference_period, "2026-03")
        self.assertEqual(result.latest_tonnes, Decimal("180"))
        self.assertEqual(result.year_over_year_pct, Decimal("20.0"))
        self.assertEqual(result.five_year_average_tonnes, Decimal("130"))
        self.assertEqual(
            result.five_year_deviation_pct,
            Decimal("38.46153846153846153846153846"),
        )
        self.assertEqual(result.baseline_periods[0], "2021-03")

    def test_requires_all_five_consecutive_baseline_observations(self) -> None:
        observations = {
            "2020-07": Decimal("100"),
            "2021-07": Decimal("110"),
            "2022-07": None,
            "2023-07": Decimal("130"),
            "2024-07": Decimal("140"),
            "2025-07": Decimal("150"),
            "2026-07": Decimal("180"),
        }
        result = compare_same_snapshot(observations)
        self.assertIsNone(result.five_year_average_tonnes)
        self.assertIsNone(result.five_year_deviation_pct)

    def test_rejects_mixed_snapshot_periods(self) -> None:
        with self.assertRaisesRegex(ValueError, "one snapshot period"):
            compare_same_snapshot(
                {"2025-03": Decimal("10"), "2026-07": Decimal("12")}
            )


if __name__ == "__main__":
    unittest.main()
