from __future__ import annotations

import re
from datetime import datetime

from agsure.crop_conditions.common import (
    CropConditionObservation,
    ReportMetadata,
    parser_error,
)


PROVINCE = "Saskatchewan"
SOURCE_URL = (
    "https://www.saskatchewan.ca/business/agriculture-natural-resources-and-industry/"
    "agribusiness-farmers-and-ranchers/market-and-trade-statistics/"
    "crops-statistics/crop-report"
)
REGIONS = (
    ("Provincial", "provincial"),
    ("South East", "south-east"),
    ("South West", "south-west"),
    ("East Central", "east-central"),
    ("West Central", "west-central"),
    ("North East", "north-east"),
    ("North West", "north-west"),
)
CROPS = {
    "Spring Wheat": "spring-wheat",
    "Durum": "durum-wheat",
    "Barley": "barley",
    "Canola": "canola",
    # Saskatchewan's exact source term is not assumed definitionally
    # equivalent to Statistics Canada's dry-peas series.
    "Field Pea": "field-peas",
}
CATEGORIES = ("excellent", "good", "fair", "poor", "very poor")
PRIMARY_HEADER = "Winter Wheat Fall Rye Spring Wheat Durum Oats Barley Flax Canola"
SECONDARY_HEADER = "Triticale Mustard Soybean Lentil Field Pea Canaryseed Chickpea"


def _tokens(line: str) -> list[str]:
    return re.findall(r"No Response\(s\)|\d{1,3}%", line)


def parse(text: str, metadata: ReportMetadata) -> list[CropConditionObservation]:
    if metadata.province != PROVINCE:
        raise ValueError(f"Saskatchewan adapter received {metadata.province!r} metadata")
    title = re.search(
        r"Saskatchewan Crop Conditions\s*-?\s*([A-Za-z]+ \d{1,2}) to "
        r"([A-Za-z]+ \d{1,2}, \d{4})",
        text,
    )
    if not title:
        raise parser_error(PROVINCE, metadata.source_document_url, "reporting period", "Saskatchewan Crop Conditions")
    end = datetime.strptime(title.group(2), "%B %d, %Y").date()
    start = datetime.strptime(
        f"{title.group(1)}, {end.year}", "%B %d, %Y"
    ).date()
    if (start.isoformat(), end.isoformat()) != (
        metadata.reporting_period_start,
        metadata.reporting_period_end,
    ):
        raise ValueError(
            f"Saskatchewan parser failed for {metadata.source_document_url}: "
            "reporting period does not match metadata"
        )
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    primary_indexes = [index for index, line in enumerate(lines) if line == PRIMARY_HEADER]
    secondary_blocks = sum(line == SECONDARY_HEADER for line in lines)
    primary_blocks = len(primary_indexes)
    if (primary_blocks, secondary_blocks) != (7, 7):
        raise parser_error(
            PROVINCE,
            metadata.source_document_url,
            "seven regional crop-condition table blocks",
            f"headers found primary={primary_blocks}, secondary={secondary_blocks}",
        )

    observations: list[CropConditionObservation] = []
    region_lookup = dict(REGIONS)
    seen_regions: list[str] = []
    for block_number, primary_index in enumerate(primary_indexes, start=1):
        source_region = next(
            (line for line in reversed(lines[max(0, primary_index - 3):primary_index]) if line in region_lookup),
            "",
        )
        if not source_region:
            raise parser_error(PROVINCE, metadata.source_document_url, "official region heading", f"regional block {block_number}")
        seen_regions.append(source_region)
        region_id = region_lookup[source_region]
        block_end = primary_indexes[block_number] if block_number < len(primary_indexes) else len(lines)
        section_lines = lines[primary_index + 1:block_end]
        try:
            secondary_index = section_lines.index(SECONDARY_HEADER)
        except ValueError:
            raise parser_error(PROVINCE, metadata.source_document_url, SECONDARY_HEADER, f"regional block {block_number}")
        primary_lines = section_lines[:secondary_index]
        secondary_lines = section_lines[secondary_index + 1:]
        primary_rows = {category: _tokens(next((line for line in primary_lines if line.startswith(category)), "")) for category in CATEGORIES}
        secondary_rows = {category: _tokens(next((line for line in secondary_lines if line.startswith(category)), "")) for category in CATEGORIES}
        if any(len(primary_rows[category]) != 8 for category in CATEGORIES):
            raise parser_error(PROVINCE, metadata.source_document_url, "eight primary crop values per category", f"regional block {block_number}")
        if any(len(secondary_rows[category]) != 7 for category in CATEGORIES):
            raise parser_error(PROVINCE, metadata.source_document_url, "seven secondary crop values per category", f"regional block {block_number}")
        crop_columns = {
            "Spring Wheat": (primary_rows, 2),
            "Durum": (primary_rows, 3),
            "Barley": (primary_rows, 5),
            "Canola": (primary_rows, 7),
            "Field Pea": (secondary_rows, 4),
        }
        for source_crop, (rows, column) in crop_columns.items():
            for category in CATEGORIES:
                source_value = rows[category][column]
                unavailable = source_value == "No Response(s)"
                observations.append(
                    CropConditionObservation(
                        **metadata.__dict__,
                        source_region=source_region,
                        source_region_id=region_id,
                        geography_level="province" if region_id == "provincial" else "official region",
                        commodity=CROPS[source_crop],
                        source_crop=source_crop,
                        observation_type="crop-condition",
                        source_measure="Crop Conditions",
                        category=category,
                        source_value=source_value,
                        value="" if unavailable else source_value.removesuffix("%"),
                        source_unit="%",
                        unit="percent",
                        baseline_type="current",
                        baseline_period="",
                        observation_status="unavailable (No Response(s))" if unavailable else "reported estimate",
                        source_page="1" if block_number <= 4 else "2",
                        source_table="Crop Conditions Table 2026",
                        source_section=source_region,
                        source_note="",
                    )
                )
    if set(seen_regions) != set(region_lookup) or len(seen_regions) != len(set(seen_regions)):
        raise parser_error(
            PROVINCE,
            metadata.source_document_url,
            f"each official region exactly once: {sorted(region_lookup)!r}",
            f"region headings {seen_regions!r}",
        )
    return observations
