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

## Statistics Canada processed observations

`data/processed/statcan_crop_production.csv` is a long-form local artifact. Raw
and normalized values are deliberately separate.

| Field | Meaning |
|---|---|
| `publisher` | Official publisher (`Statistics Canada`) |
| `source_table` | Statistics Canada table number (`32-10-0359-01`) |
| `product_id` | Statistics Canada product ID (`32100359`) |
| `source_url` | Full-table CSV ZIP URL |
| `release_date` | Release date shown on the table page when retrieved |
| `retrieved_at` | UTC retrieval timestamp in ISO 8601 format |
| `reference_period` | Source `REF_DATE`; annual crop reference year |
| `commodity` | Canonical AgSure commodity slug |
| `source_crop` | Unchanged Statistics Canada crop label |
| `geography` | Source geography label |
| `dguid` | Statistics Canada dissemination geography identifier |
| `metric` | `seeded-area`, `harvested-area`, `yield`, or `production` |
| `source_value` | Unscaled source `VALUE`; blank stays blank |
| `source_unit` | Unchanged source `UOM` |
| `scalar_factor` | Unchanged source `SCALAR_FACTOR` |
| `value` | Scalar-adjusted metric value; blank when source is blank |
| `unit` | Internal metric unit: hectares, tonnes/hectare, or tonnes |
| `observation_status` | Statistical nature of the value (`estimated`) |
| `status_marker` | Unchanged source `STATUS`, including unavailable (`..`) and quality markers |
| `symbol` | Unchanged source `SYMBOL`; revisions currently appear as `r` here |
| `terminated` | Unchanged source `TERMINATED` marker |
| `decimals` | Source display precision |
| `vector` | Statistics Canada vector identifier |
| `coordinate` | Statistics Canada cube coordinate |

Scalar factors are applied before unit conversion. Yield is converted from
kilograms per hectare to tonnes per hectare by multiplying by `0.001`. The
source value and unit remain available to reproduce that transformation.

## Statistics Canada stock observations

`data/processed/statcan_crop_stocks.csv` is a separate long-form artifact. It
is never adapted into the synthetic score input.

| Field | Meaning |
|---|---|
| `publisher` | Official publisher (`Statistics Canada`) |
| `source_table` | Statistics Canada table number (`32-10-0007-01`) |
| `product_id` | Statistics Canada product ID (`32100007`) |
| `source_url` | Validated official full-table CSV ZIP URL |
| `release_date` | Release date shown on the table page at retrieval |
| `retrieved_at` | UTC retrieval timestamp in ISO 8601 format |
| `reference_period` | Unchanged source `REF_DATE` (`YYYY-03`, `YYYY-07`, or `YYYY-12`) |
| `reference_date` | Source-defined month-end snapshot as an ISO date |
| `snapshot_period` | `March 31`, `July 31`, or `December 31` |
| `commodity` | AgSure slug: `barley`, `canola`, `durum-wheat`, or `dry-peas` |
| `source_crop` | Unchanged Statistics Canada crop label |
| `geography` | Unchanged source geography label |
| `dguid` | Statistics Canada dissemination geography identifier |
| `stock_type` | Unchanged source type-of-stock label |
| `original_value` | Unscaled source `VALUE`; blank stays blank |
| `original_unit` | Unchanged source `UOM` (`Metric tonnes`) |
| `scalar_factor` | Unchanged source `SCALAR_FACTOR` |
| `normalized_tonnes` | Scalar-adjusted tonnes; blank for unpublished values |
| `normalized_unit` | Internal metric unit (`tonnes`) |
| `observation_status` | Statistical nature of the value (`estimated` or `modelled`) |
| `status_marker` | Unchanged source `STATUS`, including `..` and `x` |
| `symbol` | Unchanged source `SYMBOL`, including revision markers |
| `terminated` | Unchanged source `TERMINATED` marker |
| `decimals` | Source display precision |
| `vector` | Statistics Canada vector identifier |
| `coordinate` | Statistics Canada cube coordinate |

Spring wheat is intentionally absent: the table's “Wheat, all excluding durum
wheat” series is not equivalent to spring wheat.
