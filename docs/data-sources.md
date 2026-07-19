# Approved data-source registry

Only official, licensed, and documented sources may feed production indicators.
This registry distinguishes implemented and planned connectors.

## Statistics Canada

### Principal field-crop area, yield, and production

Status: **implemented in v0.2**

- Publisher: Statistics Canada
- Product ID: `32100359`
- Table: `32-10-0359-01`
- Frequency: Annual
- Initial use: seeded area, harvested area, yield, and production for barley,
  canola, spring wheat, durum wheat, and dry peas
- Full-table CSV pattern:
  `https://www150.statcan.gc.ca/n1/en/tbl/csv/32100359-eng.zip`
- Table page used for the release date:
  `https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3210035901`
- Implemented geographies: Canada, Alberta, Saskatchewan, Manitoba
- Implemented crops: barley, canola (rapeseed), spring wheat, durum wheat,
  dry peas
- Implemented measures: seeded area, harvested area, yield, production

The source table describes its values as estimates. AgSure therefore records
`observation_status=estimated` even though Statistics Canada is the official
publisher. Source `STATUS`, `SYMBOL`, and `TERMINATED` fields are preserved
separately; in the current extract, revised observations carry `r` in `SYMBOL`.
Missing source values remain missing and keep their source status, symbol, and
termination fields.

### Principal field-crop stocks

Status: **implemented in v0.3**

- Publisher: Statistics Canada
- Product ID: `32100007`
- Table: `32-10-0007-01`
- Initial use: stocks by reporting date for barley, canola, durum wheat, and
  dry peas
- Validated full-table CSV URL:
  `https://www150.statcan.gc.ca/n1/tbl/csv/32100007-eng.zip`
- Table page:
  `https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3210000701`
- Implemented geographies: Canada, Alberta, Saskatchewan, Manitoba
- Exact crop labels: `Barley`, `Canola (rapeseed)`, `Wheat, durum`, `Peas, dry`
- Exact stock labels: `Farm and commercial, total`, `Farm stocks`,
  `Commercial stocks`
- Reference snapshots: March 31, July 31, December 31

The live full cube was inspected on 2026-07-19. It publishes all three stock
types for Canada and farm stocks for the selected provinces. Geography/type
combinations are retained only where rows exist in the source. The cube has no
spring-wheat-specific member. `Wheat, all excluding durum wheat` includes more
than spring wheat and is deliberately excluded rather than relabelled.

### Supply and disposition of grains in Canada

Status: **implemented in v0.4**

- Publisher: Statistics Canada
- Product ID: `32100013`
- Table: `32-10-0013-01`
- Validated full-table CSV URL:
  `https://www150.statcan.gc.ca/n1/tbl/csv/32100013-eng.zip`
- Table page:
  `https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3210001301`
- Frequency shown by the source: Occasional Monthly
- Implemented geography: exact source member `Canada`
- Exact crop labels: `Barley`, `Canola`, `Durum wheat`, `Dry peas`
- Reference snapshots: `March`, `July`, `December`

The live full cube and its included metadata file were inspected on 2026-07-19.
The archive URL returned `32100013.csv` and `32100013_MetaData.csv`; the table
page and metadata both showed a 2026-05-06 release and coverage from 1996-12
through 2026-03. The current cube uses `Metric tonnes` with a `thousands`
scalar for all rows. Source `STATUS` values in the full cube were blank, `..`,
or `x`; `SYMBOL` was blank in the current vintage. AgSure nevertheless
preserves all source status, symbol, and termination fields rather than
assuming future releases will have the same set.

The exact measure labels retained wherever a selected crop publishes them are:

- `Total supplies`
- `Total beginning stocks`
- `Beginning stocks on farms`
- `Beginning stocks in commercial positions`
- `Production`
- `Imports`
- `Total disposition`
- `Total exports`
- `Grain exports`
- `Product exports`
- `Total domestic disappearance`
- `Human food`
- `Seed requirements`
- `Industrial use`
- `Loss in handling`
- `Animal feed, waste and dockage`
- `Other domestic disappearance`
- `Total ending stocks`
- `Ending stocks on farms`
- `Ending stocks in commercial positions`

These labels are not combined or renamed. Not every crop publishes every
member: barley and durum wheat publish 19 of the 20 labels (not `Other domestic
disappearance`); canola publishes 17; and dry peas publishes 14. In particular,
AgSure does not synthesize `Human food`, `Industrial use`, or `Animal feed,
waste and dockage` for dry peas when the cube provides only `Other domestic
disappearance`.

Source note 2 states that all grains except soybeans use the August–July crop
year and that the periods are cumulative: March is August through March, July
is August through July, and December is August through December. This applies
to all four selected crops. The current cube contains `All wheat`, `Durum
wheat`, and `Wheat, excluding durum`, but no spring-wheat-specific member.
`All wheat` and `Wheat, excluding durum` are excluded rather than used as a
spring-wheat proxy.

Processed rows retain the relevant metadata note IDs. In addition to the
crop-year note, these identify crop-specific qualifications such as export seed
coverage, residual calculation of `Animal feed, waste and dockage`, commercial
stock coverage, canola handling gains and licensed positions, the dry-pea trade
definition, the three-times-a-year update schedule, and grain-equivalent
product exports. The full note text remains in the cached raw metadata CSV.

## Ingestion requirements

- Store the downloaded file's SHA-256 digest.
- Retain the release and retrieval dates.
- Store revision markers instead of stripping them.
- Keep the raw download outside Git.
- Never combine stocks from different reporting dates without an explicit
  transformation.
- Add a fixture-based parser test before loading observations into PostgreSQL.

## Cache and transformation

`python -m agsure.statcan` downloads the full ZIP into `data/raw/statcan/`,
records retrieval time, release date and SHA-256 in a sidecar JSON file, then
writes `data/processed/statcan_crop_production.csv`. Both directories are local
caches and are excluded from Git.

The normalized file is long-form: one row per reference period, geography,
crop, and metric. Source `VALUE`, `UOM`, and `SCALAR_FACTOR` remain unchanged in
their own columns. AgSure separately applies the published scalar and converts
kilograms per hectare to tonnes per hectare. Areas remain hectares and
production remains tonnes. No missing observation is interpolated or repaired.

The full-table ZIP is the source of row data. The release date is read from the
official table page at retrieval time because it is not a row field in the
full-table CSV. The release date therefore describes the downloaded table
release, not the historical date when each individual vector was first issued.

`python -m agsure.statcan_stocks` applies the same cache, digest, release-date,
and atomic-output controls to product `32100007`. Its normalized long-form file
keeps the source value and unit separate from scalar-adjusted tonnes. Missing,
unavailable, unreliable, and confidential rows remain blank while their source
status markers remain available. The derived `reference_date` is the table's
explicit month-end snapshot date, not an interpolated observation.

`observation_status=modelled` is assigned to farm-stock rows where Statistics
Canada explicitly identifies a modelled method: selected provincial March rows
from 2023 onward and July farm-stock rows from 2025 onward. Other rows remain
`estimated`; mixed total rows are not relabelled as wholly modelled.

`python -m agsure.statcan_supply_disposition` uses the same verified cache and
atomic-output pattern for product `32100013`, then writes a separate
`data/processed/statcan_supply_disposition.csv`. The raw ZIP contains the full
table and source metadata; it remains outside Git. Published values are marked
`official` because the table does not label them estimates, while unavailable,
confidential, unreliable, not-applicable, and below-detection rows receive
explicit observation statuses and retain the unchanged source marker. The
release date is the release of the retrieved cube. Historical rows from that
cube are the latest revised vintage, not a point-in-time archive.

The live-data review found one early-series anomaly: dry-pea production and
beginning-stock components are literal zeroes in 1998-12 and 1999-03 but
nonzero in 1999-07 for the same 1998/1999 crop year. Those rows have no source
status marker. They remain unchanged and should not be treated as additive
snapshots or silently repaired.

The committed offline fixture contains synthetic source-shaped test rows only;
it is not a substitute for, or redistribution of, the official full table.
