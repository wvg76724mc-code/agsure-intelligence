# Data dictionary

## Demonstration input

| Field | Meaning | Unit |
|---|---|---|
| `commodity` | Canonical AgSure commodity slug | text |
| `crop_year` | Harvest/crop year label | year |
| `seeded_area_kha` | Seeded area | thousand hectares |
| `harvested_area_kha` | Harvested area | thousand hectares |
| `yield_t_ha` | Harvested yield | tonnes/hectare |
| `production_kt` | Production | thousand tonnes |
| `carryout_kt` | Ending stocks | thousand tonnes |
| `total_use_kt` | Domestic use plus exports | thousand tonnes |
| `precip_pct_normal` | Growing-season precipitation | percent of normal |
| `gdd_pct_normal` | Growing-degree-day accumulation | percent of normal |
| `status` | Observation classification | synthetic/official/estimate/forecast/modelled |

The five accepted slugs are `barley`, `canola`, `spring-wheat`, `durum-wheat`,
and `dry-peas`. Statistics Canada's principal table aggregates dry peas; it
does not establish that all reported production is yellow peas.

Production is retained as a source observation rather than silently
recalculated from rounded area and yield values.
