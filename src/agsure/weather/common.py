from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping, Sequence

from agsure.weather.config import STATIONS_BY_CLIMATE_ID, StationContract


PARSER_VERSION = "0.8.0"
SCHEMA_VERSION = 1
PUBLICATION_VERSION = 1
ARTIFACT_MANIFEST_VERSION = 1
GENERATION_MANIFEST = "generation.json"
PUBLISHER = "Environment and Climate Change Canada"
DATASET_TITLE = "Climate - Daily Observations"
COLLECTION_URL = "https://api.weather.gc.ca/collections/climate-daily"
STATION_COLLECTION_URL = "https://api.weather.gc.ca/collections/climate-stations"
TECHNICAL_DOCUMENTATION_URL = (
    "https://climate.weather.gc.ca/doc/Technical_Documentation.pdf"
)
GDD_FORMULA = "max(((daily maximum temperature + daily minimum temperature) / 2) - base temperature, 0)"
GDD_METHODOLOGY_VERSION = "0.8.0"
DEFAULT_GDD_BASE_C = Decimal("5")

SOURCE_ELEMENTS = {
    "MAX_TEMPERATURE": ("001", "°C", "degrees Celsius"),
    "MIN_TEMPERATURE": ("002", "°C", "degrees Celsius"),
    "MEAN_TEMPERATURE": ("003", "°C", "degrees Celsius"),
    "TOTAL_PRECIPITATION": ("012", "mm", "millimetres"),
}
FLAG_FIELDS = {name: f"{name}_FLAG" for name in SOURCE_ELEMENTS}
TEMPERATURE_FLAGS = {None, "E", "M", "N", "Y"}
PRECIPITATION_FLAGS = {None, "A", "C", "E", "F", "L", "M", "T"}

STATION_PROPERTY_FIELDS = {
    "STN_ID", "STATION_NAME", "PROV_STATE_TERR_CODE", "ENG_PROV_NAME",
    "FRE_PROV_NAME", "COUNTRY", "LATITUDE", "LONGITUDE", "TIMEZONE",
    "ELEVATION", "CLIMATE_IDENTIFIER", "TC_IDENTIFIER", "WMO_IDENTIFIER",
    "STATION_TYPE", "NORMAL_CODE", "PUBLICATION_CODE", "DISPLAY_CODE",
    "ENG_STN_OPERATOR_ACRONYM", "FRE_STN_OPERATOR_ACRONYM",
    "ENG_STN_OPERATOR_NAME", "FRE_STN_OPERATOR_NAME", "FIRST_DATE",
    "LAST_DATE", "HLY_FIRST_DATE", "HLY_LAST_DATE", "DLY_FIRST_DATE",
    "DLY_LAST_DATE", "MLY_FIRST_DATE", "MLY_LAST_DATE",
    "HAS_MONTHLY_SUMMARY", "HAS_NORMALS_DATA", "HAS_HOURLY_DATA",
}
DAILY_PROPERTY_FIELDS = {
    "CLIMATE_IDENTIFIER", "COOLING_DEGREE_DAYS", "COOLING_DEGREE_DAYS_FLAG",
    "DIRECTION_MAX_GUST", "DIRECTION_MAX_GUST_FLAG", "HEATING_DEGREE_DAYS",
    "HEATING_DEGREE_DAYS_FLAG", "ID", "LOCAL_DATE", "LOCAL_DAY",
    "LOCAL_MONTH", "LOCAL_YEAR", "MAX_REL_HUMIDITY", "MAX_REL_HUMIDITY_FLAG",
    "MAX_TEMPERATURE", "MAX_TEMPERATURE_FLAG", "MEAN_TEMPERATURE",
    "MEAN_TEMPERATURE_FLAG", "MIN_REL_HUMIDITY", "MIN_REL_HUMIDITY_FLAG",
    "MIN_TEMPERATURE", "MIN_TEMPERATURE_FLAG", "PROVINCE_CODE",
    "SNOW_ON_GROUND", "SNOW_ON_GROUND_FLAG", "SPEED_MAX_GUST",
    "SPEED_MAX_GUST_FLAG", "STATION_NAME", "STN_ID", "TOTAL_PRECIPITATION",
    "TOTAL_PRECIPITATION_FLAG", "TOTAL_RAIN", "TOTAL_RAIN_FLAG", "TOTAL_SNOW",
    "TOTAL_SNOW_FLAG",
}
DAILY_OPTIONAL_PROPERTY_FIELDS = {"SOURCE"}

OUTPUT_FIELDS = (
    "schema_version", "publisher", "dataset_title", "source_url",
    "technical_documentation_url", "retrieved_at", "release_date",
    "release_date_status", "reference_date", "station_identifier_type",
    "station_identifier", "source_station_id", "wmo_identifier",
    "tc_identifier", "official_station_name", "latitude", "longitude",
    "elevation", "elevation_unit", "province", "geographic_scope",
    "station_operator", "station_type", "observation_origin",
    "source_element_identifier", "source_element_label", "raw_source_value",
    "raw_source_unit", "normalized_value", "normalized_unit",
    "observation_status", "source_quality_flag",
    "source_revision_or_estimate_flag", "revision_status",
    "transformation_identifier", "transformation_description",
    "gdd_base_temperature_c", "methodology_version", "input_max_key",
    "input_min_key", "generation_identifier", "parser_version",
)


@dataclass(frozen=True)
class WeatherObservation:
    schema_version: str
    publisher: str
    dataset_title: str
    source_url: str
    technical_documentation_url: str
    retrieved_at: str
    release_date: str
    release_date_status: str
    reference_date: str
    station_identifier_type: str
    station_identifier: str
    source_station_id: str
    wmo_identifier: str
    tc_identifier: str
    official_station_name: str
    latitude: str
    longitude: str
    elevation: str
    elevation_unit: str
    province: str
    geographic_scope: str
    station_operator: str
    station_type: str
    observation_origin: str
    source_element_identifier: str
    source_element_label: str
    raw_source_value: str
    raw_source_unit: str
    normalized_value: str
    normalized_unit: str
    observation_status: str
    source_quality_flag: str
    source_revision_or_estimate_flag: str
    revision_status: str
    transformation_identifier: str
    transformation_description: str
    gdd_base_temperature_c: str
    methodology_version: str
    input_max_key: str
    input_min_key: str
    generation_identifier: str
    parser_version: str = PARSER_VERSION

    def as_row(self) -> dict[str, str]:
        return asdict(self)


def observation_key(item: WeatherObservation | Mapping[str, str]) -> tuple[str, ...]:
    get = (lambda field: getattr(item, field)) if isinstance(item, WeatherObservation) else item.__getitem__
    return (
        get("station_identifier_type"), get("station_identifier"),
        get("reference_date"), get("observation_origin"),
        get("source_element_identifier"),
    )


def key_text(item: WeatherObservation) -> str:
    return json.dumps(observation_key(item), separators=(",", ":"))


def _decimal_text(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Weather source value is not numeric: {value!r}")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError(f"Weather source value is not finite: {value!r}")
    return format(result, "f")


def _status(element: str, value: object, flag: object) -> tuple[str, str]:
    allowed = PRECIPITATION_FLAGS if element == "TOTAL_PRECIPITATION" else TEMPERATURE_FLAGS
    if flag not in allowed:
        raise ValueError(f"Unknown {element} flag: {flag!r}")
    if flag == "M":
        if value is not None:
            raise ValueError(f"Missing flag has a value for {element}")
        return "missing", ""
    if flag in {"N", "Y"}:
        if element != "MIN_TEMPERATURE" or value is not None:
            raise ValueError(f"Incompatible {element} flag: {flag!r}")
        return ("unavailable_above_freezing" if flag == "N" else "unavailable_below_freezing"), ""
    if value is None:
        raise ValueError(f"Null {element} value lacks a documented missing flag")
    raw = _decimal_text(value)
    if element == "TOTAL_PRECIPITATION" and Decimal(raw) < 0:
        raise ValueError("Total precipitation cannot be negative")
    if flag is None:
        return "official", raw
    if flag == "E":
        return "estimated", raw
    if flag == "A":
        return "accumulated", raw
    if flag == "F":
        return "accumulated_estimated", raw
    if flag == "C":
        if Decimal(raw) != 0:
            raise ValueError("Uncertain precipitation flag C must carry source value zero")
        return "amount_uncertain", ""
    if flag == "L":
        if Decimal(raw) not in {Decimal("0"), Decimal("0.1")}:
            raise ValueError("Uncertain precipitation flag L has an unexpected value")
        return "occurrence_uncertain", ""
    if flag == "T":
        if Decimal(raw) != 0:
            raise ValueError("Trace precipitation must carry source value zero")
        return "trace", ""
    raise AssertionError("unreachable weather flag")


def validate_station_response(payload: object, expected: StationContract) -> dict[str, object]:
    if not isinstance(payload, dict) or set(payload) < {"type", "features", "numberMatched"}:
        raise ValueError("Malformed ECCC station response")
    features = payload["features"]
    if payload["type"] != "FeatureCollection" or payload["numberMatched"] != 1 or not isinstance(features, list) or len(features) != 1:
        raise ValueError("ECCC station response did not identify exactly one station")
    feature = features[0]
    if not isinstance(feature, dict) or set(feature) < {"type", "geometry", "properties"} or feature["type"] != "Feature":
        raise ValueError("Malformed ECCC station feature")
    properties = feature["properties"]
    geometry = feature["geometry"]
    if not isinstance(properties, dict) or set(properties) != STATION_PROPERTY_FIELDS:
        raise ValueError("Unexpected ECCC station schema")
    if not isinstance(geometry, dict) or geometry.get("type") != "Point" or not isinstance(geometry.get("coordinates"), list) or len(geometry["coordinates"]) != 2:
        raise ValueError("Malformed ECCC station geometry")
    longitude, latitude = (Decimal(str(value)) for value in geometry["coordinates"])
    expected_pairs = {
        "CLIMATE_IDENTIFIER": expected.climate_id, "STN_ID": int(expected.station_id),
        "STATION_NAME": expected.name, "PROV_STATE_TERR_CODE": "AB",
        "ENG_PROV_NAME": "ALBERTA", "COUNTRY": "CAN",
        "ELEVATION": expected.elevation_m, "WMO_IDENTIFIER": expected.wmo_id,
        "TC_IDENTIFIER": expected.tc_id, "STATION_TYPE": expected.station_type,
        "ENG_STN_OPERATOR_NAME": expected.operator,
    }
    if any(properties.get(field) != value for field, value in expected_pairs.items()):
        raise ValueError(f"ECCC station identity changed for {expected.climate_id}")
    if latitude != Decimal(expected.latitude) or longitude != Decimal(expected.longitude):
        raise ValueError(f"ECCC station coordinates changed for {expected.climate_id}")
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("ECCC station coordinates are invalid")
    if not str(properties["DLY_FIRST_DATE"]).startswith(expected.daily_first_date):
        raise ValueError(f"ECCC station operating period changed for {expected.climate_id}")
    return feature


def _base_observation(
    station: StationContract, reference_date: str, retrieved_at: str,
    source_url: str, generation: str,
) -> dict[str, str]:
    return {
        "schema_version": str(SCHEMA_VERSION), "publisher": PUBLISHER,
        "dataset_title": DATASET_TITLE, "source_url": source_url,
        "technical_documentation_url": TECHNICAL_DOCUMENTATION_URL,
        "retrieved_at": retrieved_at, "release_date": "",
        "release_date_status": "unavailable_from_source",
        "reference_date": reference_date, "station_identifier_type": "ECCC Climate ID",
        "station_identifier": station.climate_id, "source_station_id": station.station_id,
        "wmo_identifier": station.wmo_id, "tc_identifier": station.tc_id,
        "official_station_name": station.name, "latitude": station.latitude,
        "longitude": station.longitude, "elevation": station.elevation_m,
        "elevation_unit": "metres", "province": "Alberta",
        "geographic_scope": "individual weather station", "station_operator": station.operator,
        "station_type": station.station_type,
        "revision_status": "unavailable_from_source",
        "gdd_base_temperature_c": "", "methodology_version": "",
        "input_max_key": "", "input_min_key": "", "generation_identifier": generation,
    }


def parse_daily_response(
    payload: object, station: StationContract, start: date, end: date,
    *, retrieved_at: str, source_url: str, generation: str,
) -> list[WeatherObservation]:
    if not isinstance(payload, dict) or set(payload) < {"type", "features", "numberMatched", "numberReturned"}:
        raise ValueError("Malformed ECCC daily response")
    features = payload["features"]
    if payload["type"] != "FeatureCollection" or not isinstance(features, list):
        raise ValueError("Malformed ECCC daily response")
    if payload["numberMatched"] != len(features) or payload["numberReturned"] != len(features):
        raise ValueError("ECCC daily response is partial or paginated")
    by_date: dict[date, dict[str, object]] = {}
    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "Feature" or set(feature) < {"geometry", "properties"}:
            raise ValueError("Malformed ECCC daily feature")
        properties = feature["properties"]
        geometry = feature["geometry"]
        property_fields = frozenset(properties) if isinstance(properties, dict) else frozenset()
        if property_fields not in {
            frozenset(DAILY_PROPERTY_FIELDS),
            frozenset(DAILY_PROPERTY_FIELDS | DAILY_OPTIONAL_PROPERTY_FIELDS),
        }:
            raise ValueError("Unexpected ECCC daily schema")
        if properties["CLIMATE_IDENTIFIER"] != station.climate_id or str(properties["STN_ID"]) != station.station_id or properties["STATION_NAME"] != station.name or properties["PROVINCE_CODE"] != "AB":
            raise ValueError("Cross-station contamination in ECCC daily response")
        if not isinstance(geometry, dict) or geometry.get("type") != "Point" or geometry.get("coordinates") != [float(station.longitude), float(station.latitude)]:
            raise ValueError("ECCC daily response station geometry is mismatched")
        try:
            reference = date.fromisoformat(str(properties["LOCAL_DATE"])[:10])
        except ValueError as exc:
            raise ValueError("Invalid ECCC daily reference date") from exc
        if not (start <= reference <= end):
            raise ValueError("Cross-date contamination in ECCC daily response")
        if (
            properties["LOCAL_YEAR"] != reference.year
            or properties["LOCAL_MONTH"] != reference.month
            or properties["LOCAL_DAY"] != reference.day
            or properties["ID"]
            != f"{station.climate_id}.{reference.year}.{reference.month}.{reference.day}"
        ):
            raise ValueError("ECCC daily response date fields are mismatched")
        if reference in by_date:
            raise ValueError("Duplicate ECCC daily station/date observation")
        by_date[reference] = properties

    observations: list[WeatherObservation] = []
    current = start
    while current <= end:
        properties = by_date.get(current)
        for label, (element_id, raw_unit, normalized_unit) in SOURCE_ELEMENTS.items():
            base = _base_observation(station, current.isoformat(), retrieved_at, source_url, generation)
            if properties is None:
                raw_value = normalized_value = flag = ""
                status = "unavailable_source_date_absent"
            else:
                value = properties[label]
                flag_value = properties[FLAG_FIELDS[label]]
                status, normalized_value = _status(label, value, flag_value)
                raw_value = "" if value is None else _decimal_text(value)
                flag = "" if flag_value is None else str(flag_value)
            observations.append(WeatherObservation(
                **base, observation_origin="source_published",
                source_element_identifier=element_id, source_element_label=label,
                raw_source_value=raw_value, raw_source_unit=raw_unit,
                normalized_value=normalized_value, normalized_unit=normalized_unit,
                observation_status=status, source_quality_flag=flag,
                source_revision_or_estimate_flag=(
                    flag if status in {"estimated", "accumulated_estimated"} else ""
                ),
                transformation_identifier="identity_metric_v1",
                transformation_description=(
                    "Source metric value retained without numeric conversion; raw and normalized fields remain separate."
                ),
            ))
        current += timedelta(days=1)

    by_identity: dict[tuple[str, str], list[WeatherObservation]] = {}
    for item in observations:
        by_identity.setdefault((item.station_identifier, item.reference_date), []).append(item)
    for inputs in by_identity.values():
        observations.append(calculate_daily_gdd(inputs))
    validate_observations(observations, expected_generation=generation)
    return observations


def calculate_daily_gdd(
    inputs: Sequence[WeatherObservation], *, base_temperature_c: Decimal = DEFAULT_GDD_BASE_C
) -> WeatherObservation:
    if not inputs:
        raise ValueError("GDD requires temperature inputs")
    if not base_temperature_c.is_finite():
        raise ValueError("GDD base temperature must be finite")
    keys = [observation_key(item) for item in inputs]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate GDD input observations")
    stations = {(item.station_identifier_type, item.station_identifier) for item in inputs}
    dates = {item.reference_date for item in inputs}
    if len(stations) != 1:
        raise ValueError("GDD inputs contain mixed stations")
    if len(dates) != 1:
        raise ValueError("GDD inputs contain mixed dates")
    maximums = [item for item in inputs if item.source_element_identifier == "001"]
    minimums = [item for item in inputs if item.source_element_identifier == "002"]
    if len(maximums) != 1 or len(minimums) != 1:
        raise ValueError("GDD requires exactly one maximum and one minimum input")
    maximum, minimum = maximums[0], minimums[0]
    if maximum.normalized_unit != "degrees Celsius" or minimum.normalized_unit != "degrees Celsius":
        raise ValueError("GDD inputs have incompatible units")
    reason = ""
    value = ""
    if maximum.observation_status != "official" or minimum.observation_status != "official" or not maximum.normalized_value or not minimum.normalized_value:
        reason = "unavailable_required_inputs"
    else:
        try:
            result = max(
                ((Decimal(maximum.normalized_value) + Decimal(minimum.normalized_value)) / Decimal("2")) - base_temperature_c,
                Decimal("0"),
            )
        except InvalidOperation as exc:
            raise ValueError("GDD input is nonnumeric") from exc
        value = format(result, "f")
    return replace(
        maximum, observation_origin="calculated",
        source_element_identifier="agsure:daily-gdd-v1",
        source_element_label="DAILY_GROWING_DEGREE_DAYS",
        raw_source_value="", raw_source_unit="", normalized_value=value,
        normalized_unit="degree-days Celsius", observation_status=("calculated" if value else reason),
        source_quality_flag="", source_revision_or_estimate_flag="",
        transformation_identifier="daily_gdd_v1",
        transformation_description=GDD_FORMULA,
        gdd_base_temperature_c=format(base_temperature_c, "f"),
        methodology_version=GDD_METHODOLOGY_VERSION,
        input_max_key=key_text(maximum), input_min_key=key_text(minimum),
    )


def validate_observations(
    observations: Sequence[WeatherObservation], *, expected_generation: str | None = None
) -> None:
    if not observations:
        raise ValueError("Weather artifact has no observations")
    keys: set[tuple[str, ...]] = set()
    station_dates: dict[tuple[str, str], set[str]] = {}
    for item in observations:
        key = observation_key(item)
        if key in keys:
            raise ValueError(f"Duplicate weather observation key: {key!r}")
        keys.add(key)
        if item.station_identifier not in STATIONS_BY_CLIMATE_ID:
            raise ValueError("Weather observation has an unconfigured station")
        station = STATIONS_BY_CLIMATE_ID[item.station_identifier]
        if item.official_station_name != station.name or item.source_station_id != station.station_id:
            raise ValueError("Weather observation station identity is mismatched")
        try:
            reference = date.fromisoformat(item.reference_date)
            latitude = Decimal(item.latitude)
            longitude = Decimal(item.longitude)
            elevation = Decimal(item.elevation)
        except (ValueError, InvalidOperation) as exc:
            raise ValueError("Weather observation metadata is malformed") from exc
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180 and elevation.is_finite()):
            raise ValueError("Weather observation coordinates or elevation are invalid")
        if expected_generation is not None and item.generation_identifier != expected_generation:
            raise ValueError("Weather generation identifier is mismatched")
        if item.release_date or item.release_date_status != "unavailable_from_source":
            raise ValueError("Weather release date contract is invalid")
        if item.revision_status != "unavailable_from_source":
            raise ValueError("Weather revision contract is invalid")
        try:
            if item.normalized_value and not Decimal(item.normalized_value).is_finite():
                raise InvalidOperation
        except InvalidOperation as exc:
            raise ValueError("Weather normalized value is nonnumeric") from exc
        if item.observation_origin == "source_published":
            expected = SOURCE_ELEMENTS.get(item.source_element_label)
            if expected is None or item.source_element_identifier != expected[0] or item.raw_source_unit != expected[1] or item.normalized_unit != expected[2]:
                raise ValueError("Weather source element contract is invalid")
            status_contracts = {
                "official": ("", True, True),
                "estimated": ("E", True, True),
                "accumulated": ("A", True, True),
                "accumulated_estimated": ("F", True, True),
                "amount_uncertain": ("C", True, False),
                "occurrence_uncertain": ("L", True, False),
                "trace": ("T", True, False),
                "missing": ("M", False, False),
                "unavailable_above_freezing": ("N", False, False),
                "unavailable_below_freezing": ("Y", False, False),
                "unavailable_source_date_absent": ("", False, False),
            }
            contract = status_contracts.get(item.observation_status)
            if contract is None:
                raise ValueError("Weather observation status is unrecognized")
            flag, has_raw, has_normalized = contract
            if (
                item.source_quality_flag != flag
                or item.source_revision_or_estimate_flag
                != (flag if item.observation_status in {"estimated", "accumulated_estimated"} else "")
                or bool(item.raw_source_value) != has_raw
                or bool(item.normalized_value) != has_normalized
            ):
                raise ValueError("Weather status, flag, and value contract is invalid")
            if item.source_element_label != "TOTAL_PRECIPITATION" and item.observation_status in {
                "accumulated", "accumulated_estimated", "amount_uncertain",
                "occurrence_uncertain", "trace",
            }:
                raise ValueError("Weather precipitation flag is attached to temperature")
        elif item.observation_origin == "calculated":
            if item.source_element_identifier != "agsure:daily-gdd-v1" or item.observation_status not in {"calculated", "unavailable_required_inputs"}:
                raise ValueError("Weather calculated observation contract is invalid")
            if bool(item.normalized_value) != (item.observation_status == "calculated"):
                raise ValueError("Weather GDD status and value disagree")
            try:
                max_key = tuple(json.loads(item.input_max_key))
                min_key = tuple(json.loads(item.input_min_key))
            except (json.JSONDecodeError, TypeError) as exc:
                raise ValueError("Weather GDD input provenance is malformed") from exc
            common_identity = (
                item.station_identifier_type, item.station_identifier,
                item.reference_date, "source_published",
            )
            if max_key != (*common_identity, "001") or min_key != (*common_identity, "002"):
                raise ValueError("Weather GDD input provenance is mismatched")
        else:
            raise ValueError("Weather observation origin is invalid")
        station_dates.setdefault((item.station_identifier, reference.isoformat()), set()).add(item.source_element_identifier)
    required = {value[0] for value in SOURCE_ELEMENTS.values()} | {"agsure:daily-gdd-v1"}
    if any(elements != required for elements in station_dates.values()):
        raise ValueError("Weather station/date element set is partial")


def artifact_text(observations: Iterable[WeatherObservation]) -> tuple[str, int, str]:
    rows = list(observations)
    validate_observations(rows)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=OUTPUT_FIELDS)
    writer.writeheader()
    writer.writerows(item.as_row() for item in rows)
    text = buffer.getvalue()
    return text, len(rows), hashlib.sha256(text.encode("utf-8")).hexdigest()
