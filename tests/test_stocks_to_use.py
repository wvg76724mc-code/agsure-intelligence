import csv
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agsure.statcan_supply_disposition import normalize_rows
from agsure.stocks_to_use import (
    DOMESTIC_DISAPPEARANCE,
    ENDING_STOCKS,
    OUTPUT_FIELDS,
    RECONCILIATION_TOLERANCE_TONNES,
    TOTAL_DISPOSITION,
    TOTAL_EXPORTS,
    calculate_rows,
    rebuild,
    summarize_history,
)
from tests.test_statcan_supply_disposition import metadata


FIXTURE = Path("tests/fixtures/statcan_32100013_stocks_to_use.csv")


def fixture_rows() -> list[dict[str, str]]:
    with FIXTURE.open(newline="", encoding="utf-8") as handle:
        return list(normalize_rows(csv.DictReader(handle), metadata()))


def source_row(measure: str, value: str, **changes: str) -> dict[str, str]:
    row = next(item for item in fixture_rows() if item["measure"] == measure)
    row["normalized_tonnes"] = value
    row.update(changes)
    return row


class StocksToUseCalculationTests(unittest.TestCase):
    def test_uses_exact_three_measure_formula_and_preserves_provenance(self) -> None:
        rows = list(calculate_rows(fixture_rows()))
        barley = next(row for row in rows if row["commodity"] == "barley")

        self.assertEqual(barley["ending_stocks_tonnes"], "1500000")
        self.assertEqual(barley["total_exports_tonnes"], "3000000")
        self.assertEqual(
            barley["total_domestic_disappearance_tonnes"], "4500000"
        )
        self.assertEqual(barley["total_use_tonnes"], "7500000")
        self.assertEqual(barley["stocks_to_use_pct"], "20")
        self.assertEqual(barley["calculation_status"], "calculated")
        self.assertEqual(barley["ending_stocks_source_original_value"], "1500.0")
        self.assertEqual(barley["ending_stocks_source_vector"], "v5104")
        self.assertEqual(barley["ending_stocks_source_coordinate"], "1.5.18")
        self.assertEqual(barley["ending_stocks_source_revision_marker"], "r")

    def test_reconciles_with_explicit_source_precision_tolerance(self) -> None:
        barley = next(
            row for row in calculate_rows(fixture_rows()) if row["commodity"] == "barley"
        )

        self.assertEqual(RECONCILIATION_TOLERANCE_TONNES.as_tuple().exponent, 0)
        self.assertEqual(barley["reconciliation_difference_tonnes"], "100")
        self.assertEqual(barley["reconciliation_tolerance_tonnes"], "200")
        self.assertEqual(barley["reconciliation_status"], "reconciled")
        self.assertEqual(barley["total_disposition_source_vector"], "v5101")

    def test_flags_large_reconciliation_difference_without_suppressing_ratio(self) -> None:
        rows = [
            source_row(ENDING_STOCKS, "1500000"),
            source_row(TOTAL_EXPORTS, "3000000"),
            source_row(DOMESTIC_DISAPPEARANCE, "4500000"),
            source_row(TOTAL_DISPOSITION, "8999700"),
        ]

        result = list(calculate_rows(rows))[0]

        self.assertEqual(result["calculation_status"], "calculated")
        self.assertEqual(result["stocks_to_use_pct"], "20")
        self.assertEqual(result["reconciliation_difference_tonnes"], "300")
        self.assertEqual(result["reconciliation_status"], "unreconciled")

    def test_unpublished_required_input_returns_unavailable_with_reason(self) -> None:
        dry_peas = next(
            row
            for row in calculate_rows(fixture_rows())
            if row["commodity"] == "dry-peas"
        )

        self.assertEqual(dry_peas["calculation_status"], "unavailable")
        self.assertEqual(dry_peas["stocks_to_use_pct"], "")
        self.assertIn("Total exports is unavailable", dry_peas["calculation_reason"])
        self.assertEqual(dry_peas["total_exports_source_status_marker"], "..")
        self.assertEqual(
            dry_peas["total_exports_source_observation_status"], "unavailable"
        )

    def test_confidential_status_rejects_even_an_erroneously_populated_value(self) -> None:
        rows = [
            source_row(ENDING_STOCKS, "1500000"),
            source_row(
                TOTAL_EXPORTS,
                "3000000",
                observation_status="confidential",
                status_marker="x",
            ),
            source_row(DOMESTIC_DISAPPEARANCE, "4500000"),
        ]

        result = list(calculate_rows(rows))[0]

        self.assertEqual(result["calculation_status"], "unavailable")
        self.assertIn("confidential", result["calculation_reason"])

    def test_absent_input_returns_unavailable_and_never_substitutes(self) -> None:
        rows = [
            source_row(ENDING_STOCKS, "1500000"),
            source_row(TOTAL_EXPORTS, "3000000"),
        ]

        result = list(calculate_rows(rows))[0]

        self.assertEqual(result["calculation_status"], "unavailable")
        self.assertIn(
            "required input absent: Total domestic disappearance",
            result["calculation_reason"],
        )

    def test_all_structurally_absent_inputs_still_emit_unavailable_year(self) -> None:
        row = source_row(ENDING_STOCKS, "1500000")
        row["measure"] = "Total supplies"

        result = list(calculate_rows([row]))[0]

        self.assertEqual(result["calculation_status"], "unavailable")
        for measure in (ENDING_STOCKS, TOTAL_EXPORTS, DOMESTIC_DISAPPEARANCE):
            self.assertIn(
                f"required input absent: {measure}", result["calculation_reason"]
            )

    def test_rejects_zero_or_negative_total_use(self) -> None:
        for exports, domestic in (("0", "0"), ("-2", "1")):
            with self.subTest(exports=exports, domestic=domestic):
                rows = [
                    source_row(ENDING_STOCKS, "100"),
                    source_row(TOTAL_EXPORTS, exports),
                    source_row(DOMESTIC_DISAPPEARANCE, domestic),
                ]
                result = list(calculate_rows(rows))[0]
                self.assertEqual(result["calculation_status"], "unavailable")
                self.assertIn("must be positive", result["calculation_reason"])

    def test_mismatched_optional_disposition_is_not_used_for_reconciliation(self) -> None:
        rows = [
            source_row(ENDING_STOCKS, "1500000"),
            source_row(TOTAL_EXPORTS, "3000000"),
            source_row(DOMESTIC_DISAPPEARANCE, "4500000"),
            source_row(TOTAL_DISPOSITION, "9000000", normalized_unit="kilograms"),
        ]

        result = list(calculate_rows(rows))[0]

        self.assertEqual(result["calculation_status"], "calculated")
        self.assertEqual(result["reconciliation_status"], "not_available")
        self.assertEqual(result["total_disposition_tonnes"], "")

    def test_nonnumeric_and_wrong_unit_are_unavailable(self) -> None:
        rows = [
            source_row(ENDING_STOCKS, "not-a-number"),
            source_row(TOTAL_EXPORTS, "300", normalized_unit="kilograms"),
            source_row(DOMESTIC_DISAPPEARANCE, "400"),
        ]

        result = list(calculate_rows(rows))[0]

        self.assertEqual(result["calculation_status"], "unavailable")
        self.assertIn("nonnumeric", result["calculation_reason"])
        self.assertIn("normalized_unit='kilograms'", result["calculation_reason"])

    def test_never_combines_different_reference_periods(self) -> None:
        domestic = source_row(DOMESTIC_DISAPPEARANCE, "4500000")
        domestic["reference_period"] = "2024-07"
        domestic["crop_year"] = "2023/2024"
        rows = [
            source_row(ENDING_STOCKS, "1500000"),
            source_row(TOTAL_EXPORTS, "3000000"),
            domestic,
        ]

        results = list(calculate_rows(rows))

        self.assertEqual(len(results), 2)
        self.assertTrue(all(row["calculation_status"] == "unavailable" for row in results))

    def test_ignores_march_and_december_snapshots(self) -> None:
        rows = fixture_rows()
        for row in rows:
            row["snapshot_period"] = "March"

        self.assertEqual(list(calculate_rows(rows)), [])

    def test_rejects_malformed_july_crop_year_relationship(self) -> None:
        rows = fixture_rows()
        for row in rows:
            if row["commodity"] == "barley":
                row["crop_year"] = "2023/2024"

        barley = next(
            row for row in calculate_rows(rows) if row["commodity"] == "barley"
        )

        self.assertEqual(barley["calculation_status"], "unavailable")
        self.assertIn("not the July completion", barley["calculation_reason"])

    def test_duplicate_source_measure_fails_closed(self) -> None:
        row = source_row(ENDING_STOCKS, "100")

        with self.assertRaisesRegex(ValueError, "Duplicate source observation"):
            list(calculate_rows([row, deepcopy(row)]))

    def test_rebuild_writes_one_row_per_crop_year_atomically(self) -> None:
        normalized = fixture_rows()
        with TemporaryDirectory() as directory:
            input_path = Path(directory) / "normalized.csv"
            output_path = Path(directory) / "derived.csv"
            with input_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=normalized[0].keys())
                writer.writeheader()
                writer.writerows(normalized)
            count = rebuild(input_path, output_path)
            with output_path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                output_rows = list(reader)

        self.assertEqual(count, 2)
        self.assertEqual(tuple(reader.fieldnames or ()), OUTPUT_FIELDS)
        self.assertEqual(len(output_rows), 2)
        self.assertEqual(
            len({(row["commodity"], row["crop_year"]) for row in output_rows}), 2
        )


class StocksToUseHistoryTests(unittest.TestCase):
    def _history(self, ratios: dict[int, str]) -> list[dict[str, str]]:
        return [
            {
                "crop_year": f"{year}/{year + 1}",
                "calculation_status": "calculated",
                "stocks_to_use_pct": ratio,
            }
            for year, ratio in ratios.items()
        ]

    def test_previous_change_and_strict_five_year_average(self) -> None:
        summary = summarize_history(
            self._history({2019: "10", 2020: "12", 2021: "14", 2022: "16", 2023: "18", 2024: "15"})
        )

        self.assertEqual(str(summary.previous_ratio), "18")
        self.assertEqual(str(summary.previous_change_percentage_points), "-3")
        self.assertEqual(str(summary.five_year_average_ratio), "14")
        self.assertEqual(str(summary.five_year_deviation_percentage_points), "1")

    def test_missing_prior_year_suppresses_only_affected_comparisons(self) -> None:
        summary = summarize_history(
            self._history({2019: "10", 2020: "12", 2022: "16", 2023: "18", 2024: "15"})
        )

        self.assertEqual(str(summary.previous_ratio), "18")
        self.assertIsNone(summary.five_year_average_ratio)
        self.assertIsNone(summary.five_year_deviation_percentage_points)


if __name__ == "__main__":
    unittest.main()
