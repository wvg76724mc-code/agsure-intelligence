from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agsure.io import load_observations


class InputTests(unittest.TestCase):
    def test_loads_and_orders_sample(self) -> None:
        observations = load_observations("sample_data/crops_synthetic.csv")
        self.assertEqual(len(observations), 30)
        self.assertEqual(
            {item.commodity for item in observations},
            {"barley", "canola", "spring-wheat", "durum-wheat", "dry-peas"},
        )
        self.assertEqual(observations[-1].status, "synthetic")

    def test_rejects_missing_columns(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            path.write_text("crop_year,value\n2025,10\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Missing required columns"):
                load_observations(path)

    def test_rejects_duplicate_years(self) -> None:
        header = (
            "commodity,crop_year,seeded_area_kha,harvested_area_kha,yield_t_ha,"
            "production_kt,carryout_kt,total_use_kt,precip_pct_normal,"
            "gdd_pct_normal,status\n"
        )
        row = "barley,2025,1,1,1,1,1,1,100,100,synthetic\n"
        with TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.csv"
            path.write_text(header + row + row, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "commodity and crop_year"):
                load_observations(path)


if __name__ == "__main__":
    unittest.main()
