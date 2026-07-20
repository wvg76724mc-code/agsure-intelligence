# Data dictionary

## Official regional crop conditions

`data/processed/crop_conditions.csv` is a separate normalized long-form
artifact. It never enters `CropYearObservation`, stocks-to-use, or the synthetic
supply-pressure calculation.

| Field | Meaning |
|---|---|
| `publisher`, `source_program`, `source_report_title` | Publisher and exact report identity |
| `source_url`, `source_document_url` | Canonical program page and exact document |
| `source_document_sha256` | Digest of the locally verified source document |
| `release_date`, `retrieved_at` | Source release and UTC retrieval vintage |
| `reporting_period_start`, `reporting_period_end`, `crop_year` | Published period; start is blank when Alberta publishes only an as-of date |
| `province` | Publisher jurisdiction, never inferred from a region name |
| `source_region`, `source_region_id`, `geography_level` | Unchanged label, province-scoped stable identifier, and official level |
| `commodity` | Exact internal crop identity; Saskatchewan `Field Pea` is `field-peas`, distinct from Statistics Canada `dry-peas` |
| `source_crop` | Unchanged crop label such as `Field Pea` or `Dry Peas` |
| `observation_type`, `source_measure`, `category` | Normalized type plus exact source measure/category labels |
| `source_value`, `value` | Unchanged display value and separate normalized numeric text |
| `source_unit`, `unit` | Exact `%` and normalized `percent`; no condition score conversion |
| `baseline_type`, `baseline_period` | `current` for retained v0.7 rows; source baselines remain separate when implemented |
| `observation_status` | `estimated`, `reported estimate`, or explicit unavailable wording |
| `extraction_method` | `embedded_pdf_text`; OCR is not used |
| `source_page`, `source_table`, `source_section`, `source_note` | Page/table/section provenance and necessary note |
| `revision_marker` | Source revision marker when present; blank is not interpreted as unrevised forever |
| `parser_version` | Adapter contract version (`0.7.0`) |

The normalized key includes province, region ID, commodity, observation type,
source measure, category, unit, baseline identity, and reporting period. Region
IDs are province-scoped: Alberta `south` is not Saskatchewan `south-east`, and
Manitoba `southwest` is neither one. Missing source cells retain their raw token
and status while normalized `value` remains blank.

`crop_conditions.manifest.json` records the artifact filename, SHA-256-backed
generation, schema version, and row count. The reader requires an exact match;
the CSV is unavailable if publication was interrupted or either file is stale.

## Unified overview view model

`agsure.unified_overview` reads the four normalized or derived local artifacts
and returns immutable presentation objects; it does not import Streamlit or
alter source rows. A displayed observation contains `label`, a `Decimal` value
or explicit absence, `unit`, `reference_period`, optional `crop_year`,
`geography`, `source_table`, `source_url`, `release_date`, `retrieved_at`,
`publisher`, `observation_kind`, exact `source_label`, and the unchanged source
row as `provenance`.

`observation_kind` distinguishes `Official published observation`, `Official
input to derived calculation`, and `Derived official calculation`. Synthetic
demonstration rows do not enter this model. `SeriesView.reason` records why an
artifact or exact series is unavailable. `identity` records the selected
geography, measure or stock type, and snapshot boundary. Artifact contracts
reject missing required columns, duplicate normalized keys, wrong source
tables, aggregate crop aliases, wrong units, and inconsistent reference,
snapshot, or crop-year identities.

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

## Statistics Canada supply-and-disposition observations

`data/processed/statcan_supply_disposition.csv` is a separate long-form local
artifact and is never adapted into the synthetic score input.

| Field | Meaning |
|---|---|
| `publisher` | Official publisher (`Statistics Canada`) |
| `source_table` | Statistics Canada table number (`32-10-0013-01`) |
| `product_id` | Statistics Canada product ID (`32100013`) |
| `source_url` | Validated official full-table CSV ZIP URL |
| `table_url` | Official human-readable table page |
| `release_date` | Release date shown on the table page at retrieval |
| `retrieved_at` | UTC retrieval timestamp in ISO 8601 format |
| `reference_period` | Unchanged source `REF_DATE` (`YYYY-03`, `YYYY-07`, or `YYYY-12`) |
| `snapshot_period` | Derived selector label: `March`, `July`, or `December` |
| `crop_year` | Explicit August–July relationship (`YYYY/YYYY`) derived from the source note |
| `reporting_period_start` | August crop-year start at month precision (`YYYY-08`) |
| `reporting_period_end` | Selected source reference period at month precision |
| `reporting_period_basis` | `Cumulative over the crop year`, following source note 2 |
| `commodity` | AgSure slug: `barley`, `canola`, `durum-wheat`, or `dry-peas` |
| `source_crop` | Unchanged source crop label |
| `geography` | Unchanged source geography label (`Canada`) |
| `dguid` | Statistics Canada dissemination geography identifier |
| `source_note_ids` | Relevant table and crop-member note IDs in the cached metadata CSV |
| `measure` | Unchanged `Supply and disposition of grains` member label |
| `original_value` | Unchanged source `VALUE`; unpublished text or blank stays traceable |
| `original_unit` | Unchanged source `UOM` (`Metric tonnes`) |
| `uom_id` | Unchanged source `UOM_ID` |
| `scalar_factor` | Unchanged source `SCALAR_FACTOR` (`thousands`) |
| `scalar_id` | Unchanged source `SCALAR_ID` |
| `normalized_tonnes` | Scalar-adjusted tonnes; blank for unpublished observations |
| `normalized_unit` | Internal metric unit (`tonnes`) |
| `observation_status` | `official` for published values; otherwise the explicit missing/publication condition |
| `status_marker` | Unchanged source `STATUS` |
| `revision_marker` | `r` only when an unchanged source status or symbol carries `r` |
| `symbol` | Unchanged source `SYMBOL` |
| `terminated` | Unchanged source `TERMINATED` marker |
| `decimals` | Source display precision |
| `vector` | Statistics Canada vector identifier |
| `coordinate` | Statistics Canada cube coordinate |

The derived crop-year fields make the source relationship explicit without
changing `reference_period`. March and July belong to the crop year that began
in the prior calendar year; December belongs to the crop year beginning in the
same calendar year. No day of month is invented because this table publishes
month-level reference periods.

## Official stocks-to-use calculations

`data/processed/statcan_stocks_to_use.csv` is a local derived artifact with one
row per selected commodity and completed crop year. It is rebuilt from the
normalized supply-and-disposition CSV and is never used by the synthetic score.

| Field | Meaning |
|---|---|
| `publisher`, `source_table`, `product_id`, `source_url`, `table_url` | Official source identity inherited from the matched rows |
| `source_release_date`, `source_retrieval_date` | Latest cube release and retrieval vintage used by the calculation |
| `source_vintage_basis` | Explicit latest-revised-cube interpretation |
| `reference_period`, `snapshot_period`, `crop_year` | Exact July reference period and completed August–July crop year |
| `reporting_period_start`, `reporting_period_end`, `reporting_period_basis` | Source-derived cumulative crop-year period identity |
| `commodity`, `source_crop`, `geography`, `dguid`, `source_note_ids` | Exact series identity and source-note references |
| `ending_stocks_tonnes` | Normalized `Total ending stocks` numerator |
| `total_exports_tonnes` | First normalized denominator component |
| `total_domestic_disappearance_tonnes` | Second normalized denominator component |
| `total_use_tonnes` | `Total exports + Total domestic disappearance` |
| `stocks_to_use_pct` | `Total ending stocks / total_use_tonnes * 100` |
| `total_disposition_tonnes` | Optional exact source value used only for reconciliation |
| `reconciliation_sum_tonnes` | `total_use_tonnes + ending_stocks_tonnes` |
| `reconciliation_difference_tonnes` | Reconciliation sum minus `Total disposition`; never used to alter a source value |
| `reconciliation_tolerance_tonnes` | Inclusive 200-tonne source-precision tolerance |
| `reconciliation_status` | `reconciled`, `unreconciled`, or `not_available` |
| `calculation_status` | `calculated` or `unavailable` |
| `calculation_reason` | Explicit reason when calculation is unavailable |
| `formula`, `methodology_version` | Reproducible v0.5 calculation identity (`0.5.0`, intentionally retained) |

Each of the prefixes `ending_stocks_source_`, `total_exports_source_`,
`domestic_disappearance_source_`, and `total_disposition_source_` is followed by
the same provenance fields: `measure`, `original_value`, `original_unit`,
`uom_id`, `scalar_factor`, `scalar_id`, `normalized_tonnes`, `normalized_unit`,
`observation_status`, `status_marker`, `revision_marker`, `symbol`, `terminated`,
`decimals`, `vector`, and `coordinate`. These fields preserve the exact input
rows separately from calculated values.
