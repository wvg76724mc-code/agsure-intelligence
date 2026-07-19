import csv
from dataclasses import fields
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

from agsure.commodities import COMMODITIES
from agsure.unified_overview import (
    ArtifactPaths,
    UnifiedOverview,
    build_overview,
)


FIXTURES = Path("tests/fixtures")


def fixture_paths(root: Path = FIXTURES) -> ArtifactPaths:
    return ArtifactPaths(
        production=root / "unified_production.csv",
        stocks=root / "unified_stocks.csv",
        supply_disposition=root / "unified_supply.csv",
        stocks_to_use=root / "unified_stocks_to_use.csv",
    )


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or ()), list(reader)


def write_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class UnifiedOverviewTests(unittest.TestCase):
    def test_all_supported_commodities_and_explicit_spring_wheat_gaps(self) -> None:
        for commodity in COMMODITIES:
            with self.subTest(commodity=commodity):
                overview = build_overview(fixture_paths(), commodity)
                self.assertIsInstance(overview, UnifiedOverview)
                self.assertTrue(overview.production["production"].available)
                if commodity == "spring-wheat":
                    self.assertFalse(overview.stocks.available)
                    self.assertFalse(overview.supply_disposition.available)
                    self.assertFalse(overview.stocks_to_use.available)
                    self.assertIn(
                        "Not available from the selected official source",
                        overview.stocks.reason,
                    )
                else:
                    self.assertTrue(overview.stocks.available)
                    self.assertTrue(overview.supply_disposition.available)
                    self.assertTrue(overview.stocks_to_use.available)

    def test_spring_wheat_rejects_aggregate_wheat_identity(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for source in fixture_paths().__dict__.values():
                shutil.copy(source, root / source.name)
            production = root / "unified_production.csv"
            names, rows = read_rows(production)
            spring = next(row for row in rows if row["commodity"] == "spring-wheat")
            spring["source_crop"] = "Wheat, excluding durum"
            write_rows(production, names, rows)

            with self.assertRaisesRegex(ValueError, "incompatible crop identity"):
                build_overview(fixture_paths(root), "spring-wheat")

    def test_missing_artifact_and_missing_series_are_recorded(self) -> None:
        paths = ArtifactPaths(
            production=fixture_paths().production,
            stocks=Path("tests/fixtures/does-not-exist.csv"),
            supply_disposition=fixture_paths().supply_disposition,
            stocks_to_use=fixture_paths().stocks_to_use,
        )
        overview = build_overview(paths, "barley")

        self.assertFalse(overview.stocks.available)
        self.assertIn("artifact is missing", overview.artifact_errors["stocks"])
        self.assertTrue(overview.production["yield"].observations)
        self.assertFalse(
            build_overview(fixture_paths(), "canola").production["yield"].available
        )

    def test_canada_and_province_identities_never_cross(self) -> None:
        overview = build_overview(fixture_paths(), "barley", "Alberta")

        self.assertEqual(overview.production["production"].latest.geography, "Alberta")
        self.assertEqual(overview.stocks.latest.geography, "Alberta")
        self.assertEqual(overview.stock_type, "Farm stocks")
        self.assertEqual(overview.supply_disposition.latest.geography, "Canada")
        self.assertEqual(overview.stocks_to_use.latest.geography, "Canada")

    def test_latest_selection_is_deterministic_and_never_falls_back(self) -> None:
        first = build_overview(fixture_paths(), "barley")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for source in fixture_paths().__dict__.values():
                shutil.copy(source, root / source.name)
            production = root / "unified_production.csv"
            names, rows = read_rows(production)
            write_rows(production, names, list(reversed(rows)))
            second = build_overview(fixture_paths(root), "barley")

        self.assertEqual(
            first.production["production"].latest,
            second.production["production"].latest,
        )
        self.assertEqual(first.production["production"].latest.reference_period, "2025")

        with TemporaryDirectory() as directory:
            root = Path(directory)
            for source in fixture_paths().__dict__.values():
                shutil.copy(source, root / source.name)
            production = root / "unified_production.csv"
            names, rows = read_rows(production)
            latest = next(
                row
                for row in rows
                if row["commodity"] == "barley"
                and row["geography"] == "Canada"
                and row["metric"] == "production"
                and row["reference_period"] == "2025"
            )
            latest["value"] = ""
            write_rows(production, names, rows)
            unavailable = build_overview(fixture_paths(root), "barley")

        self.assertEqual(
            unavailable.production["production"].latest.reference_period, "2025"
        )
        self.assertFalse(unavailable.production["production"].available)

    def test_histories_are_same_period_and_same_measure_only(self) -> None:
        overview = build_overview(fixture_paths(), "barley")

        self.assertEqual(
            {item.provenance["snapshot_period"] for item in overview.stocks.observations},
            {"March 31"},
        )
        self.assertEqual(
            {
                (item.provenance["measure"], item.provenance["snapshot_period"])
                for item in overview.supply_disposition.observations
            },
            {("Total ending stocks", "July")},
        )
        self.assertEqual(overview.stocks.comparison.reference_period, "2026-03")
        self.assertEqual(
            overview.supply_disposition.comparison.reference_period, "2025-07"
        )

    def test_duplicate_and_incompatible_sources_fail_closed(self) -> None:
        for mutation, message in (("duplicate", "Duplicate"), ("table", "incompatible source table")):
            with self.subTest(mutation=mutation), TemporaryDirectory() as directory:
                root = Path(directory)
                for source in fixture_paths().__dict__.values():
                    shutil.copy(source, root / source.name)
                path = root / "unified_stocks.csv"
                names, rows = read_rows(path)
                if mutation == "duplicate":
                    rows.append(dict(rows[0]))
                else:
                    rows[0]["source_table"] = "32-10-9999-99"
                write_rows(path, names, rows)
                with self.assertRaisesRegex(ValueError, message):
                    build_overview(fixture_paths(root), "barley")

    def test_incompatible_reporting_period_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for source in fixture_paths().__dict__.values():
                shutil.copy(source, root / source.name)
            path = root / "unified_supply.csv"
            names, rows = read_rows(path)
            rows[0]["crop_year"] = "2022/2023"
            write_rows(path, names, rows)

            with self.assertRaisesRegex(ValueError, "incompatible reporting period"):
                build_overview(fixture_paths(root), "barley")

    def test_view_model_has_no_score_field_or_synthetic_input(self) -> None:
        overview = build_overview(fixture_paths(), "barley")
        names = {item.name for item in fields(overview)}

        self.assertNotIn("score", names)
        self.assertNotIn("supply_pressure", names)
        self.assertTrue(
            all("synthetic" not in item.observation_kind.lower() for item in overview.snapshot)
        )


class UnifiedDashboardAppTests(unittest.TestCase):
    def test_unified_view_runs_for_every_supported_commodity(self) -> None:
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError as exc:  # pragma: no cover - dashboard extra is required in CI
            self.fail(f"Streamlit dashboard dependency is unavailable: {exc}")

        with TemporaryDirectory() as directory:
            root = Path(directory)
            names = {
                "unified_production.csv": "statcan_crop_production.csv",
                "unified_stocks.csv": "statcan_crop_stocks.csv",
                "unified_supply.csv": "statcan_supply_disposition.csv",
                "unified_stocks_to_use.csv": "statcan_stocks_to_use.csv",
            }
            for source, destination in names.items():
                shutil.copy(FIXTURES / source, root / destination)

            import os

            previous = os.environ.get("AGSURE_PROCESSED_DIR")
            os.environ["AGSURE_PROCESSED_DIR"] = str(root)
            try:
                for commodity in COMMODITIES:
                    with self.subTest(commodity=commodity):
                        app = AppTest.from_file("src/agsure/dashboard.py").run(
                            timeout=30
                        )
                        app.selectbox(key="unified_commodity").set_value(
                            commodity
                        ).run(timeout=30)
                        self.assertEqual(list(app.exception), [])
                        self.assertEqual(app.selectbox[0].value, "unified")
                        if commodity == "spring-wheat":
                            self.assertTrue(
                                any(
                                    "Not available from the selected official source"
                                    in warning.value
                                    for warning in app.warning
                                )
                            )
            finally:
                if previous is None:
                    os.environ.pop("AGSURE_PROCESSED_DIR", None)
                else:
                    os.environ["AGSURE_PROCESSED_DIR"] = previous


if __name__ == "__main__":
    unittest.main()
