from __future__ import annotations

import io
import json
import os
import shutil
from dataclasses import replace
from datetime import date
from decimal import Decimal
from email.message import Message
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agsure.analysis import calculate_supply_pressure
from agsure.io import load_observations
from agsure.weather import ingest as weather_ingest
from agsure.weather.artifact import (
    current_pointer_path,
    publish_current_pointer,
    read_artifact,
    resolve_current_generation,
)
from agsure.weather.common import (
    GDD_FORMULA,
    calculate_daily_gdd,
    parse_daily_response,
    validate_observations,
    validate_station_response,
)
from agsure.weather.config import STATIONS, STATIONS_BY_CLIMATE_ID


FIXTURES = Path("tests/fixtures/weather")
STATION = STATIONS_BY_CLIMATE_ID["3031640"]
START = date(2025, 6, 1)
END = date(2025, 6, 3)
RETRIEVED = "2026-07-21T12:00:00Z"
SOURCE_URL = (
    "https://api.weather.gc.ca/collections/climate-daily/items?f=json&"
    "CLIMATE_IDENTIFIER=3031640&datetime=2025-06-01%2F2025-06-03&limit=1000"
)


def payload(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def parsed(generation: str = "a" * 32):
    return parse_daily_response(
        payload("claresholm_daily_synthetic.json"), STATION, START, END,
        retrieved_at=RETRIEVED, source_url=SOURCE_URL, generation=generation,
    )


def input_pair(rows, day: str = "2025-06-01"):
    return [
        row for row in rows
        if row.reference_date == day and row.source_element_identifier in {"001", "002"}
    ]


def publish_test_generation(output: Path, rows, generation: str = "b" * 32):
    root = output.parent / "weather-generations"
    staging = root / f".staging-{generation}"
    final = root / generation
    staging.mkdir(parents=True)
    updated = [replace(row, generation_identifier=generation) for row in rows]
    weather_ingest._write_processed(
        staging / "processed" / output.name, updated, generation, [], START, END
    )
    digest = weather_ingest._write_generation_manifest(staging, generation)
    staging.replace(final)
    publish_current_pointer(output, final, generation, digest)
    return resolve_current_generation(output)


def all_station_rows():
    source_rows = [row for row in parsed() if row.observation_origin == "source_published"]
    rows = []
    for station in STATIONS:
        station_sources = [
            replace(
                row, station_identifier=station.climate_id,
                source_station_id=station.station_id, wmo_identifier=station.wmo_id,
                tc_identifier=station.tc_id, official_station_name=station.name,
                latitude=station.latitude, longitude=station.longitude,
                elevation=station.elevation_m, station_operator=station.operator,
                station_type=station.station_type,
                source_url=row.source_url.replace("3031640", station.climate_id),
            )
            for row in source_rows
        ]
        rows.extend(station_sources)
        for day in ("2025-06-01", "2025-06-02", "2025-06-03"):
            rows.append(calculate_daily_gdd(input_pair(station_sources, day)))
    return rows


class WeatherParsingTests(unittest.TestCase):
    def test_station_metadata_and_exact_identity(self) -> None:
        feature = validate_station_response(
            payload("claresholm_station_synthetic.json"), STATION
        )
        self.assertEqual(feature["properties"]["CLIMATE_IDENTIFIER"], "3031640")
        self.assertEqual(feature["geometry"]["coordinates"][1], 50.00363055555555)
        changed = payload("claresholm_station_synthetic.json")
        changed["features"][0]["properties"]["STATION_NAME"] = "SUCCESSOR"
        with self.assertRaisesRegex(ValueError, "identity changed"):
            validate_station_response(changed, STATION)

    def test_exact_field_mapping_raw_normalized_and_provenance(self) -> None:
        rows = parsed()
        self.assertEqual(len(rows), 15)
        maximum = next(
            row for row in rows
            if row.reference_date == "2025-06-01" and row.source_element_identifier == "001"
        )
        precipitation = next(
            row for row in rows
            if row.reference_date == "2025-06-01" and row.source_element_identifier == "012"
        )
        self.assertEqual(maximum.source_element_label, "MAX_TEMPERATURE")
        self.assertEqual(maximum.raw_source_value, "20.4")
        self.assertEqual(maximum.raw_source_unit, "°C")
        self.assertEqual(maximum.normalized_value, "20.4")
        self.assertEqual(maximum.normalized_unit, "degrees Celsius")
        self.assertEqual(precipitation.raw_source_unit, "mm")
        self.assertEqual(precipitation.normalized_unit, "millimetres")
        self.assertEqual(maximum.publisher, "Environment and Climate Change Canada")
        self.assertEqual(maximum.source_url, SOURCE_URL)
        self.assertEqual(maximum.retrieved_at, RETRIEVED)
        self.assertEqual(maximum.release_date, "")
        self.assertEqual(maximum.release_date_status, "unavailable_from_source")
        self.assertEqual(maximum.revision_status, "unavailable_from_source")

    def test_trace_estimated_missing_and_gdd_statuses(self) -> None:
        rows = parsed()
        trace = next(
            row for row in rows
            if row.reference_date == "2025-06-02" and row.source_element_identifier == "012"
        )
        estimated = next(
            row for row in rows
            if row.reference_date == "2025-06-02" and row.source_element_identifier == "001"
        )
        missing = next(
            row for row in rows
            if row.reference_date == "2025-06-03" and row.source_element_identifier == "001"
        )
        unavailable_gdd = next(
            row for row in rows
            if row.reference_date == "2025-06-02" and row.observation_origin == "calculated"
        )
        self.assertEqual((trace.raw_source_value, trace.normalized_value), ("0", ""))
        self.assertEqual((trace.observation_status, trace.source_quality_flag), ("trace", "T"))
        self.assertEqual(estimated.observation_status, "estimated")
        self.assertEqual(missing.observation_status, "missing")
        self.assertEqual(unavailable_gdd.observation_status, "unavailable_required_inputs")
        self.assertEqual(unavailable_gdd.normalized_value, "")

    def test_absent_source_date_is_materialized_not_repaired(self) -> None:
        source = payload("claresholm_daily_synthetic.json")
        source["features"].pop(1)
        source["numberMatched"] = source["numberReturned"] = 2
        rows = parse_daily_response(
            source, STATION, START, END, retrieved_at=RETRIEVED,
            source_url=SOURCE_URL, generation="c" * 32,
        )
        absent = [row for row in rows if row.reference_date == "2025-06-02"]
        self.assertEqual(len(absent), 5)
        self.assertTrue(all(row.normalized_value == "" for row in absent))
        self.assertEqual(
            {row.observation_status for row in absent if row.observation_origin == "source_published"},
            {"unavailable_source_date_absent"},
        )

    def test_unknown_flags_malformed_schema_duplicates_and_contamination_fail(self) -> None:
        cases = []
        unknown = payload("claresholm_daily_synthetic.json")
        unknown["features"][0]["properties"]["MAX_TEMPERATURE_FLAG"] = "Q"
        cases.append((unknown, "Unknown MAX_TEMPERATURE flag"))
        drift = payload("claresholm_daily_synthetic.json")
        drift["features"][0]["properties"]["NEW_FIELD"] = "drift"
        cases.append((drift, "Unexpected ECCC daily schema"))
        duplicate = payload("claresholm_daily_synthetic.json")
        duplicate["features"].append(duplicate["features"][0])
        duplicate["numberMatched"] = duplicate["numberReturned"] = 4
        cases.append((duplicate, "Duplicate ECCC daily"))
        crossed = payload("claresholm_daily_synthetic.json")
        crossed["features"][0]["properties"]["CLIMATE_IDENTIFIER"] = "3030QLP"
        cases.append((crossed, "Cross-station"))
        partial = payload("claresholm_daily_synthetic.json")
        partial["numberMatched"] = 4
        cases.append((partial, "partial or paginated"))
        for source, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                parse_daily_response(
                    source, STATION, START, END, retrieved_at=RETRIEVED,
                    source_url=SOURCE_URL, generation="d" * 32,
                )

    def test_duplicate_normalized_key_fails(self) -> None:
        rows = parsed()
        with self.assertRaisesRegex(ValueError, "Duplicate weather observation key"):
            validate_observations([*rows, rows[0]])


class GrowingDegreeDayTests(unittest.TestCase):
    def test_formula_decimal_precision_and_provenance(self) -> None:
        result = calculate_daily_gdd(input_pair(parsed()))
        self.assertEqual(result.normalized_value, "8.55")
        self.assertEqual(result.gdd_base_temperature_c, "5")
        self.assertEqual(result.transformation_description, GDD_FORMULA)
        self.assertEqual(result.observation_status, "calculated")
        self.assertIn('"001"', result.input_max_key)
        self.assertIn('"002"', result.input_min_key)

    def test_zero_floor_negative_and_fractional_values(self) -> None:
        maximum, minimum = input_pair(parsed())
        cases = (
            ("4", "2", "0"),
            ("-2.1", "-8.3", "0"),
            ("10.01", "5.02", "2.515"),
        )
        for high, low, expected in cases:
            with self.subTest(high=high, low=low):
                result = calculate_daily_gdd([
                    replace(maximum, normalized_value=high, raw_source_value=high),
                    replace(minimum, normalized_value=low, raw_source_value=low),
                ])
                self.assertEqual(result.normalized_value, expected)

    def test_missing_flagged_wrong_units_mixed_identity_and_duplicates(self) -> None:
        maximum, minimum = input_pair(parsed())
        flagged = calculate_daily_gdd([
            replace(maximum, observation_status="estimated", source_quality_flag="E"),
            minimum,
        ])
        self.assertEqual(flagged.observation_status, "unavailable_required_inputs")
        with self.assertRaisesRegex(ValueError, "incompatible units"):
            calculate_daily_gdd([replace(maximum, normalized_unit="kelvin"), minimum])
        with self.assertRaisesRegex(ValueError, "mixed stations"):
            calculate_daily_gdd([
                maximum, replace(minimum, station_identifier=STATIONS[2].climate_id)
            ])
        with self.assertRaisesRegex(ValueError, "mixed dates"):
            calculate_daily_gdd([maximum, replace(minimum, reference_date="2025-06-02")])
        with self.assertRaisesRegex(ValueError, "Duplicate GDD input"):
            calculate_daily_gdd([maximum, maximum, minimum])
        missing = calculate_daily_gdd([replace(maximum, normalized_value="", observation_status="missing"), minimum])
        self.assertEqual(missing.normalized_value, "")


class WeatherPublicationTests(unittest.TestCase):
    def test_immutable_generation_round_trip_and_exact_schema(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "processed" / "weather.csv"
            generation = publish_test_generation(output, parsed())
            rows = read_artifact(output)
            self.assertEqual(len(rows), 15)
            self.assertEqual({row["generation_identifier"] for row in rows}, {generation.generation})

    def test_corruption_partial_generation_and_bad_pointer_fail_closed(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "processed" / "weather.csv"
            generation = publish_test_generation(output, parsed())
            generation.artifact.write_text("corrupt\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "generation file is mismatched"):
                read_artifact(output)

        with TemporaryDirectory() as directory:
            output = Path(directory) / "processed" / "weather.csv"
            generation = publish_test_generation(output, parsed())
            generation.artifact_manifest.unlink()
            with self.assertRaisesRegex(ValueError, "partial or unmanifested"):
                read_artifact(output)

        with TemporaryDirectory() as directory:
            output = Path(directory) / "processed" / "weather.csv"
            pointer = current_pointer_path(output)
            pointer.parent.mkdir(parents=True)
            pointer.write_text("not-json\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "CURRENT pointer is malformed"):
                read_artifact(output)

    def test_cached_retrieval_metadata_integrity(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source" / "daily.json"
            source.parent.mkdir()
            source.write_text("{}", encoding="utf-8")
            metadata = source.with_suffix(".json.retrieval.json")
            metadata.write_text(json.dumps({
                "source_url": SOURCE_URL, "retrieved_at": RETRIEVED,
                "sha256": "0" * 64, "byte_count": 2,
                "content_type": "application/geo+json",
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "metadata is mismatched"):
                weather_ingest._read_cached_json(
                    source, root / "destination" / "daily.json",
                    expected_url=SOURCE_URL,
                )

    def test_interruption_before_current_swap_preserves_previous_generation(self) -> None:
        station_bytes = (FIXTURES / "claresholm_station_synthetic.json").read_bytes()
        daily_bytes = (FIXTURES / "claresholm_daily_synthetic.json").read_bytes()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "processed" / "weather.csv"
            cache = root / "raw"
            with patch.object(weather_ingest, "STATIONS", (STATION,)), patch(
                "urllib.request.urlopen",
                side_effect=[FakeResponse(station_bytes), FakeResponse(daily_bytes)],
            ):
                weather_ingest.ingest(cache, output, start=START, end=END, force=True)
            previous = resolve_current_generation(output)
            previous_rows = read_artifact(output)
            pointer_bytes = current_pointer_path(output).read_bytes()
            with patch.object(weather_ingest, "STATIONS", (STATION,)), patch(
                "urllib.request.urlopen",
                side_effect=[FakeResponse(station_bytes), FakeResponse(daily_bytes)],
            ), patch.object(
                weather_ingest, "publish_current_pointer",
                side_effect=RuntimeError("interrupted before CURRENT swap"),
            ):
                with self.assertRaisesRegex(RuntimeError, "before CURRENT"):
                    weather_ingest.ingest(cache, output, start=START, end=END, force=True)
            self.assertEqual(resolve_current_generation(output).generation, previous.generation)
            self.assertEqual(read_artifact(output), previous_rows)
            self.assertEqual(current_pointer_path(output).read_bytes(), pointer_bytes)
            self.assertTrue(previous.directory.is_dir())

    def test_weather_never_enters_synthetic_score(self) -> None:
        self.assertTrue(parsed())
        barley = [
            row for row in load_observations("sample_data/crops_synthetic.csv")
            if row.commodity == "barley"
        ]
        result = calculate_supply_pressure(barley)
        self.assertEqual(result.score, Decimal("72.1"))
        self.assertNotIn("weather", {component.name for component in result.components})
        self.assertNotIn("gdd", {component.name for component in result.components})


class WeatherDashboardTests(unittest.TestCase):
    def _prepare(self, root: Path) -> None:
        names = {
            "unified_production.csv": "statcan_crop_production.csv",
            "unified_stocks.csv": "statcan_crop_stocks.csv",
            "unified_supply.csv": "statcan_supply_disposition.csv",
            "unified_stocks_to_use.csv": "statcan_stocks_to_use.csv",
        }
        for source, destination in names.items():
            shutil.copy(Path("tests/fixtures") / source, root / destination)
        publish_test_generation(root / "weather.csv", all_station_rows())

    def test_dedicated_dashboard_renders_every_configured_station(self) -> None:
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError as exc:  # pragma: no cover
            self.fail(f"Streamlit dashboard dependency is unavailable: {exc}")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._prepare(root)
            previous = os.environ.get("AGSURE_PROCESSED_DIR")
            os.environ["AGSURE_PROCESSED_DIR"] = str(root)
            try:
                for station in STATIONS:
                    with self.subTest(station=station.climate_id):
                        app = AppTest.from_file("src/agsure/dashboard.py").run(timeout=30)
                        app.selectbox[0].set_value("weather").run(timeout=30)
                        app.selectbox(key="weather_station").set_value(
                            station.climate_id
                        ).run(timeout=30)
                        app.selectbox(key=f"weather_start_{station.climate_id}").set_value(
                            "2025-06-01"
                        ).run(timeout=30)
                        app.selectbox(
                            key=f"weather_end_{station.climate_id}_2025-06-01"
                        ).set_value("2025-06-03").run(timeout=30)
                        self.assertEqual(list(app.exception), [])
                        self.assertTrue(
                            any(station.name in item.value for item in app.subheader)
                        )
            finally:
                if previous is None:
                    os.environ.pop("AGSURE_PROCESSED_DIR", None)
                else:
                    os.environ["AGSURE_PROCESSED_DIR"] = previous

    def test_missing_data_and_one_point_chart_rule(self) -> None:
        from streamlit.testing.v1 import AppTest

        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._prepare(root)
            previous = os.environ.get("AGSURE_PROCESSED_DIR")
            os.environ["AGSURE_PROCESSED_DIR"] = str(root)
            try:
                app = AppTest.from_file("src/agsure/dashboard.py").run(timeout=30)
                app.selectbox[0].set_value("weather").run(timeout=30)
                app.selectbox(key="weather_station").set_value("3031640").run(timeout=30)
                app.selectbox(key="weather_start_3031640").set_value(
                    "2025-06-03"
                ).run(timeout=30)
                app.selectbox(key="weather_end_3031640_2025-06-03").set_value(
                    "2025-06-03"
                ).run(timeout=30)
                self.assertEqual(list(app.exception), [])
                self.assertTrue(all(item.value == "Not available" for item in app.metric))
                self.assertTrue(
                    any("fewer than two dates" in item.value for item in app.caption)
                )
                self.assertEqual(len(app.get("plotly_chart")), 0)
            finally:
                if previous is None:
                    os.environ.pop("AGSURE_PROCESSED_DIR", None)
                else:
                    os.environ["AGSURE_PROCESSED_DIR"] = previous

    def test_unified_overview_requires_station_and_date(self) -> None:
        from streamlit.testing.v1 import AppTest

        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._prepare(root)
            previous = os.environ.get("AGSURE_PROCESSED_DIR")
            os.environ["AGSURE_PROCESSED_DIR"] = str(root)
            try:
                app = AppTest.from_file("src/agsure/dashboard.py").run(timeout=30)
                self.assertIsNone(app.selectbox(key="unified_weather_station").value)
                self.assertTrue(
                    any("Select an official weather station" in item.value for item in app.info)
                )
                app.selectbox(key="unified_weather_station").set_value("3031640").run(timeout=30)
                self.assertIsNone(app.selectbox(key="unified_weather_date_3031640").value)
                app.selectbox(key="unified_weather_date_3031640").set_value(
                    "2025-06-01"
                ).run(timeout=30)
                self.assertEqual(list(app.exception), [])
                self.assertTrue(
                    any("only the selected station" in item.value for item in app.warning)
                )
            finally:
                if previous is None:
                    os.environ.pop("AGSURE_PROCESSED_DIR", None)
                else:
                    os.environ["AGSURE_PROCESSED_DIR"] = previous


class FakeResponse(io.BytesIO):
    def __init__(self, value: bytes):
        super().__init__(value)
        headers = Message()
        headers.add_header("Content-Type", "application/geo+json")
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


if __name__ == "__main__":
    unittest.main()
