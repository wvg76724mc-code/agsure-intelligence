from __future__ import annotations

import re
from datetime import datetime

from agsure.crop_conditions.common import (
    CropConditionObservation,
    ReportMetadata,
    parser_error,
)


PROVINCE = "Alberta"
SOURCE_URL = "https://open.alberta.ca/publications/2830245"
REGIONS = (
    ("South", "south"),
    ("Central", "central"),
    ("N East", "north-east"),
    ("N West", "north-west"),
    ("Peace", "peace"),
    ("Alberta", "provincial"),
)
CROPS = {
    "Spring Wheat": "spring-wheat",
    "Durum": "durum-wheat",
    "Barley": "barley",
    "Canola": "canola",
    "Dry Peas": "dry-peas",
}


def parse(text: str, metadata: ReportMetadata) -> list[CropConditionObservation]:
    if metadata.province != PROVINCE:
        raise ValueError(f"Alberta adapter received {metadata.province!r} metadata")
    title_match = re.search(
        r"Alberta Crop Report\s+Crop conditions as of ([A-Za-z]+ \d{1,2}, \d{4})",
        text,
        re.MULTILINE,
    )
    if not title_match:
        raise parser_error(PROVINCE, metadata.source_document_url, "report title", "Crop conditions as of")
    report_end = datetime.strptime(title_match.group(1), "%B %d, %Y").date().isoformat()
    if report_end != metadata.reporting_period_end:
        raise ValueError(
            f"Alberta parser failed for {metadata.source_document_url}: report date "
            f"{report_end} does not match metadata {metadata.reporting_period_end}"
        )
    table_match = re.search(
        r"Table 1: Regional Crop Condition Ratings as of .*?"
        r"Per Cent Rated Good-to-Excellent Conditions(?P<table>.*?)"
        r"Source:\s*AGI/AFSC Crop Reporting Survey",
        text,
        re.DOTALL,
    )
    if not table_match:
        raise parser_error(PROVINCE, metadata.source_document_url, "Table 1", "Regional Crop Condition Ratings")

    observations: list[CropConditionObservation] = []
    row_pattern = re.compile(
        r"^\s*(?P<crop>Spring Wheat|Durum|Barley|Canola|Dry Peas)\s*\*?\s+"
        r"(?P<values>(?:\d{1,3}\.\d%|-)(?:\s+(?:\d{1,3}\.\d%|-)){5})\s*$",
        re.MULTILINE,
    )
    matches = list(row_pattern.finditer(table_match.group("table")))
    if {match.group("crop") for match in matches} != set(CROPS):
        raise parser_error(
            PROVINCE,
            metadata.source_document_url,
            f"exact crop rows {sorted(CROPS)!r}",
            "Table 1 crop labels",
        )
    for match in matches:
        source_crop = match.group("crop")
        values = match.group("values").split()
        if len(values) != len(REGIONS):
            raise parser_error(
                PROVINCE, metadata.source_document_url, "six regional values", source_crop
            )
        for (source_region, region_id), source_value in zip(REGIONS, values):
            status = "unavailable" if source_value == "-" else "reported estimate"
            value = "" if source_value == "-" else source_value.removesuffix("%")
            observations.append(
                CropConditionObservation(
                    **metadata.__dict__,
                    source_region=source_region,
                    source_region_id=region_id,
                    geography_level="province" if region_id == "provincial" else "official region",
                    commodity=CROPS[source_crop],
                    source_crop=source_crop,
                    observation_type="crop-condition",
                    source_measure="Per Cent Rated Good-to-Excellent Conditions",
                    category="good-to-excellent",
                    source_value=source_value,
                    value=value,
                    source_unit="%",
                    unit="percent",
                    baseline_type="current",
                    baseline_period="",
                    observation_status=status,
                    source_page="1",
                    source_table="Table 1: Regional Crop Condition Ratings",
                    source_section="",
                    source_note="Percentage totals may not add to 100 due to rounding.",
                )
            )
    return observations
