from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StationContract:
    climate_id: str
    station_id: str
    name: str
    latitude: str
    longitude: str
    elevation_m: str
    wmo_id: str
    tc_id: str
    station_type: str
    operator: str
    daily_first_date: str
    inclusion_reason: str


ECCC_OPERATOR = (
    "Environment and Climate Change Canada - Meteorological Service of Canada"
)

# Distinct source identities. Do not splice predecessor or successor stations.
STATIONS = (
    StationContract(
        "3031640", "2224", "CLARESHOLM", "50.00363055555555",
        "-113.63863611111111", "1009.00", "71234", "WDK", "Climate-Auto",
        ECCC_OPERATOR, "1951-08-01",
        "Foothills-transition agricultural context and a long active daily record.",
    ),
    StationContract(
        "3033875", "49268", "LETHBRIDGE", "49.63027777777778",
        "-112.79888888888888", "929.00", "71267", "YQL", "Aviation-Auto",
        "NAV Canada", "2011-01-13",
        "Major irrigated-agriculture centre; retained as its current station identity.",
    ),
    StationContract(
        "3030QLP", "2180", "BROOKS", "50.55529722222222",
        "-111.84889722222222", "747.00", "71457", "WBO", "Climate-Auto",
        ECCC_OPERATOR, "1988-12-01",
        "Eastern irrigation-district context and strong recent element continuity.",
    ),
    StationContract(
        "3030768", "10915", "BOW ISLAND", "49.734186111111114",
        "-111.45027777777777", "816.60", "71231", "WXL", "Climate-Auto",
        ECCC_OPERATOR, "1993-06-04",
        "Southeastern irrigated-production context and strong recent completeness.",
    ),
    StationContract(
        "3034485", "30347", "MEDICINE HAT RCS", "50.02511111111111",
        "-110.71725", "715.00", "71026", "XMW", "Climate-Auto",
        ECCC_OPERATOR, "2000-08-01",
        "Eastern dryland agricultural context and an active official station record.",
    ),
)

STATIONS_BY_CLIMATE_ID = {station.climate_id: station for station in STATIONS}
