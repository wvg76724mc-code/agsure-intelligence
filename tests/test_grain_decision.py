import unittest
from decimal import Decimal
from pathlib import Path

from agsure.grain_decision import (
    StorageDecisionInputs,
    calculate_storage_decision,
)


class StorageDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inputs = StorageDecisionInputs(
            quantity_bushels=Decimal(20000),
            current_bid_per_bushel=Decimal("14.00"),
            storage_months=Decimal(3),
            annual_financing_rate_pct=Decimal(8),
            storage_cost_per_bushel_month=Decimal("0.025"),
            handling_cost_per_bushel=Decimal("0.05"),
            shrink_pct=Decimal("0.30"),
        )

    def test_break_even_calculation_exposes_each_cost(self) -> None:
        result = calculate_storage_decision(self.inputs)

        self.assertEqual(result.sell_now_value, Decimal("280000.00"))
        self.assertEqual(result.retained_bushels, Decimal("19940.000"))
        self.assertEqual(result.financing_cost, Decimal("5600.0000"))
        self.assertEqual(result.storage_cost, Decimal("1500.000"))
        self.assertEqual(result.handling_cost, Decimal("1000.00"))
        self.assertEqual(result.total_carrying_cost, Decimal("8100.0000"))
        self.assertEqual(
            result.break_even_future_bid.quantize(Decimal("0.0001")),
            Decimal("14.4483"),
        )

    def test_break_even_bid_has_zero_advantage(self) -> None:
        result = calculate_storage_decision(self.inputs)
        self.assertEqual(result.advantage_at(result.break_even_future_bid), Decimal(0))

    def test_future_bid_above_break_even_has_positive_advantage(self) -> None:
        result = calculate_storage_decision(self.inputs)
        advantage = result.advantage_at(result.break_even_future_bid + Decimal("0.50"))
        self.assertEqual(advantage, result.retained_bushels * Decimal("0.50"))

    def test_rejects_invalid_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "quantity_bushels"):
            calculate_storage_decision(
                StorageDecisionInputs(
                    **{**self.inputs.__dict__, "quantity_bushels": Decimal(0)}
                )
            )
        with self.assertRaisesRegex(ValueError, "shrink_pct"):
            calculate_storage_decision(
                StorageDecisionInputs(
                    **{**self.inputs.__dict__, "shrink_pct": Decimal(100)}
                )
            )


class StorageDecisionDashboardTests(unittest.TestCase):
    def test_default_example_renders_auditable_break_even_result(self) -> None:
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError as exc:  # pragma: no cover - dashboard extra required in CI
            self.fail(f"Streamlit dashboard dependency is unavailable: {exc}")

        dashboard = Path(__file__).parents[1] / "src" / "agsure" / "dashboard.py"
        app = AppTest.from_file(str(dashboard)).run(timeout=30)
        app.selectbox[0].set_value("sell-or-store").run(timeout=30)
        app.button[0].click().run(timeout=30)

        self.assertEqual(list(app.exception), [])
        metrics = {item.label: item.value for item in app.metric}
        self.assertEqual(metrics["Sell-now gross value"], "$280,000")
        self.assertEqual(metrics["Total cost of waiting"], "$8,100")
        self.assertEqual(metrics["Break-even future bid"], "$14.45/bu")
        self.assertEqual(metrics["Required bid increase"], "$0.45/bu")


if __name__ == "__main__":
    unittest.main()
