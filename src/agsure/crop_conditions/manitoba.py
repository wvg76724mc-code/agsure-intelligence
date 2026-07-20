from __future__ import annotations

import re
from datetime import datetime

from agsure.crop_conditions.common import CropConditionObservation, ReportMetadata, parser_error


PROVINCE = "Manitoba"
SOURCE_URL = "https://www.gov.mb.ca/agriculture/crops/seasonal-reports/crop-report/"
REGIONS = ("Southwest", "Northwest", "Central", "Eastern", "Interlake")


def parse(text: str, metadata: ReportMetadata) -> list[CropConditionObservation]:
    """Validate the current report contract; retain no narrative-derived numbers."""
    if metadata.province != PROVINCE:
        raise ValueError(f"Manitoba adapter received {metadata.province!r} metadata")
    title = re.search(r"Crop Report\s*[–-]\s*([A-Za-z]+ \d{1,2}, \d{4})", text)
    if not title:
        raise parser_error(PROVINCE, metadata.source_document_url, "Crop Report title", "release date")
    release = datetime.strptime(title.group(1), "%B %d, %Y").date().isoformat()
    if release != metadata.release_date:
        raise ValueError(
            f"Manitoba parser failed for {metadata.source_document_url}: release date "
            f"{release} does not match metadata {metadata.release_date}"
        )
    for locator in ("Report compiled by Manitoba Agriculture", "Commodity Reports", "Regional Comments", *REGIONS):
        if locator not in text:
            raise parser_error(PROVINCE, metadata.source_document_url, "current report heading", locator)
    # Current reports use narrative crop stages and qualitative regional commentary.
    # Ranges such as "10 to 80% flower" are not distributions or exact regional
    # condition observations, so v0.7 intentionally emits no normalized rows.
    return []
