from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommodityDefinition:
    slug: str
    display_name: str
    statcan_name: str
    score_model_enabled: bool


COMMODITIES = {
    item.slug: item
    for item in (
        CommodityDefinition("barley", "Barley", "Barley", True),
        CommodityDefinition("canola", "Canola", "Canola (rapeseed)", False),
        CommodityDefinition(
            "spring-wheat", "Spring Wheat", "Wheat, spring", False
        ),
        CommodityDefinition("durum-wheat", "Durum Wheat", "Wheat, durum", False),
        CommodityDefinition("dry-peas", "Dry Peas", "Peas, dry", False),
    )
}


def get_commodity(slug: str) -> CommodityDefinition:
    try:
        return COMMODITIES[slug]
    except KeyError as exc:
        choices = ", ".join(COMMODITIES)
        raise ValueError(f"Unknown commodity {slug!r}; expected one of: {choices}") from exc

