from decimal import Decimal
import unittest

from agsure.analysis import calculate_supply_pressure, classify_score
from agsure.models import CropYearObservation


def observation(
    year: int,
    production: str = "100",
    carryout: str = "10",
    use: str = "100",
    precip: str = "100",
    gdd: str = "100",
) -> CropYearObservation:
    return CropYearObservation(
        commodity="barley",
        crop_year=year,
        seeded_area_kha=Decimal("30"),
        harvested_area_kha=Decimal("29"),
        yield_t_ha=Decimal("3.4"),
        production_kt=Decimal(production),
        carryout_kt=Decimal(carryout),
        total_use_kt=Decimal(use),
        precip_pct_normal=Decimal(precip),
        gdd_pct_normal=Decimal(gdd),
        status="synthetic",
    )


class SupplyPressureTests(unittest.TestCase):
    def test_baseline_conditions_score_balanced(self) -> None:
        items = [observation(year) for year in range(2020, 2026)]
        result = calculate_supply_pressure(items)
        self.assertEqual(result.score, Decimal("50.0"))
        self.assertEqual(result.classification, "balanced")

    def test_abundant_conditions_raise_score(self) -> None:
        items = [observation(year) for year in range(2020, 2025)]
        items.append(
            observation(
                2025,
                production="130",
                carryout="15",
                use="100",
                precip="115",
                gdd="105",
            )
        )
        result = calculate_supply_pressure(items)
        self.assertGreater(result.score, Decimal("70"))
        self.assertEqual(result.classification, "abundant")

    def test_requires_baseline_plus_current_year(self) -> None:
        with self.assertRaisesRegex(ValueError, "At least 6 observations"):
            calculate_supply_pressure([observation(year) for year in range(2020, 2025)])

    def test_rejects_unvalidated_crop_model(self) -> None:
        items = [
            CropYearObservation(**{**observation(year).__dict__, "commodity": "canola"})
            for year in range(2020, 2026)
        ]
        with self.assertRaisesRegex(ValueError, "not yet validated for Canola"):
            calculate_supply_pressure(items)

    def test_rejects_mixed_commodity_inputs(self) -> None:
        items = [observation(year) for year in range(2020, 2026)]
        items[-1] = CropYearObservation(
            **{**items[-1].__dict__, "commodity": "dry-peas"}
        )
        with self.assertRaisesRegex(ValueError, "exactly one commodity"):
            calculate_supply_pressure(items)

    def test_rejects_zero_total_use(self) -> None:
        item = observation(2025, use="0")
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            _ = item.stocks_to_use_pct

    def test_classification_boundaries(self) -> None:
        self.assertEqual(classify_score(Decimal("29.9")), "tight")
        self.assertEqual(classify_score(Decimal("30")), "moderately tight")
        self.assertEqual(classify_score(Decimal("45")), "balanced")
        self.assertEqual(classify_score(Decimal("55.1")), "moderately abundant")
        self.assertEqual(classify_score(Decimal("71")), "abundant")


if __name__ == "__main__":
    unittest.main()
