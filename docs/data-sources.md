# Approved data-source registry

Only official, licensed, and documented sources may feed production indicators.
This registry distinguishes implemented and planned connectors.

## Official Prairie crop reports in v0.7

Live validation was performed on 2026-07-19 against the canonical report pages
and representative documents below. Full PDFs were downloaded only to a local
temporary/cache location, verified with SHA-256, and not committed.

### Alberta Crop Reporting Program

- Publisher: Government of Alberta, Agriculture and Irrigation
- Collection: `https://open.alberta.ca/publications/2830245`
- Frequency: weekly during the crop season; the collection distinguishes full
  and abbreviated reports
- Validated full report: `Crop conditions as of July 14, 2026`, released July
  17, 2026; SHA-256
  `3f3f627bfe547e8b736c8ba3f517fdff4b9ef784bff72ea6da97744bb99661b1`
- Extraction: pypdf embedded text in layout mode; Table 1 on PDF page 1
- Regions retained exactly from Table 1: `South`, `Central`, `N East`, `N
  West`, `Peace`, `Alberta`
- Crops retained: `Spring Wheat`, `Durum`, `Barley`, `Canola`, `Dry Peas`
- Measure retained: exact source combined measure `Per Cent Rated
  Good-to-Excellent Conditions`

The report publishes `-` for unavailable crop/region cells; those remain blank
normalized values with `observation_status=unavailable`. AgSure does not split
the combined measure into categories. Table 1's `Major Crops`, `All Crops`, and
all-crops five- and ten-year averages are not mapped to an exact commodity.
Charts and narrative values are not extracted. The source notes that percentage
totals may not equal 100 due to rounding and requires accreditation to AFSC and
the Government of Alberta.

### Saskatchewan Crop Report

- Publisher: Government of Saskatchewan, Ministry of Agriculture
- Canonical page: `https://www.saskatchewan.ca/business/agriculture-natural-resources-and-industry/agribusiness-farmers-and-ranchers/market-and-trade-statistics/crops-statistics/crop-report`
- Frequency: weekly for approximately 27 growing-season weeks from April 1
- Validated table: `Saskatchewan Crop Conditions - July 7 to July 13, 2026`;
  SHA-256
  `3afd5da1a550586fe4be2e927576089c0659fdc38024ed0920e40b6547e1525c`
- Extraction: pypdf embedded text in layout mode; two-page `Crop Conditions
  Table 2026`
- Regions retained: `Provincial`, `South East`, `South West`, `East Central`,
  `West Central`, `North East`, `North West`
- Crops retained: `Spring Wheat`, `Durum`, `Barley`, `Canola`, `Field Pea`
- Categories retained: exact lowercase `excellent`, `good`, `fair`, `poor`,
  and `very poor`

The source's `No Response(s)` is retained as an unavailable status and is never
filled. Each available five-category distribution is checked against 100 per
cent with a one-percentage-point rounding tolerance. `Field Pea` uses the
distinct regional identity `field-peas`; the unchanged source term is preserved
and it is never joined to Statistics Canada's `dry-peas` series. No definitional
equivalence is claimed. Crop-development aggregates
such as `Spring Cereals`, maps, and narrative pages are not crop-specific
substitutes.

### Manitoba Crop Report

- Publisher: Government of Manitoba, Manitoba Agriculture
- Canonical page: `https://www.gov.mb.ca/agriculture/crops/seasonal-reports/crop-report/`
- Frequency: weekly growing-season PDFs; the page exposes current and annual
  archives
- Validated report: `Crop Report - July 14, 2026`; SHA-256
  `eb0b9bc5135256647ad5194aa7f992898c1e72c1b05cc75e0586744cef2e681a`
- Official report regions: `Southwest`, `Northwest`, `Central`, `Eastern`, and
  `Interlake`
- Official reporting-area definition map:
  `https://www.gov.mb.ca/agriculture/crops/seasonal-reports/pubs/crop-report-map.pdf`
  (`Manitoba Agricultural Reporting`, dated April 6, 2020)
- Extraction status: current format contract validated, numeric grain-crop
  observations unsupported in v0.7

The representative report provides crop stages and regional observations in
narrative prose, sometimes as ranges. It does not provide an exact structured
crop-by-region condition distribution comparable to Alberta or Saskatchewan.
AgSure emits no Manitoba numeric rows, does not infer values from phrases such
as “good,” and shows an explicit unavailable state. The agronomic narrative
does not publish an exact reporting-period start/end separate from the report
date, so AgSure does not borrow the weather table's July 6–12 period. The structured weather
table is not ingested because weather belongs to v0.8.
The map associates municipal areas with the five reporting districts. AgSure
retains only the district label and does not convert it into a municipality,
town, census division, or another province's region.

### History and format risk

Coverage is intentionally limited to the three representative July 2026
documents above; it is not a complete historical series. Current-report URLs
represent the latest retrieved documents, not point-in-time web archives.
Alberta abbreviated reports, changed historical layouts, Saskatchewan table
geometry, and Manitoba narrative structure are explicit format-drift risks.
Every adapter checks titles, periods, exact table/header counts, crop labels,
regions, and units and fails closed when a locator changes.

Similarly named regions in different provinces are different publisher-defined
geographies. They are never translated, joined, or averaged. No provincial
value is calculated from regions and no Prairie condition score is calculated.
AgSure stores structured facts and short labels only; it does not redistribute
full reports or long narrative passages. The dashboard links to the canonical
document and exposes page/table provenance. Alberta's accreditation note is
preserved in documentation, and all publishers remain explicitly attributed.

## Unified overview use in v0.7

The overview is a read-only presentation of the existing processed artifacts;
it is not another ingestion pipeline and does not redownload a source. The
production table is available for all five supported commodities where the
exact member exists. Stocks, supply and disposition, and derived stocks-to-use
are available for barley, canola, durum wheat, and dry peas. They are explicitly
unavailable for spring wheat because neither aggregate wheat nor wheat excluding
durum is an exact spring-wheat member.

For every exact identity, the overview selects the greatest reference period
deterministically and does not fall back when that newest row is blank or
unusable. Stocks retain one source stock type and compare one month-end snapshot
across years. Supply and disposition retain one exact source measure and one
cumulative snapshot across years. Stocks-to-use retains exact Canada, July,
completed August–July crop years. The displayed release and retrieval dates
describe the local cube vintage; historical rows are the latest revised values
in that vintage, not a point-in-time archive.

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

Crop reports use separate Alberta, Saskatchewan, and Manitoba adapters. Only
download/cache/digest, embedded-text extraction, validation, and atomic-output
utilities are shared. `python -m agsure.crop_conditions.ingest` stages each new
PDF under `data/raw/crop_conditions/` and promotes it with retrieval metadata
only after successful extraction and parsing. It writes the processed CSV and
a manifest sharing an artifact SHA-256 generation. Readers reject missing,
stale, or mismatched manifests, including an interrupted two-file publication.
A failed parser cannot replace a prior valid cache or processed artifact. Tests
use clearly marked synthetic source-shaped fixtures and require no network.

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

### Derived official stocks-to-use history

Status: **implemented in v0.5**

This derived artifact uses the existing normalized product `32100013` CSV and
does not trigger another download. It selects exact `Canada` July rows for
barley, canola, durum wheat, and dry peas. The exact numerator is `Total ending
stocks`; the denominator is `Total exports + Total domestic disappearance`.
`Total disposition` is retained only for reconciliation because the cube
structure shows that it also contains ending stocks.

The official table page and bundled metadata note 2 were verified before
implementation. Note 2 defines July as August through July for these crops, so
only July represents a completed crop year. The cube dimension metadata places
`Total exports`, `Total domestic disappearance`, and `Total ending stocks` as
members beneath `Total disposition`. Historical results reflect the latest
revised cube vintage at retrieval, not point-in-time vintage reconstruction.

The derived CSV retains the release date, retrieval date, vectors, coordinates,
source values, units, scalars, observation statuses, source markers, and
revision markers for each required input and for the optional reconciliation
row. Unavailable inputs remain unavailable. No aggregate wheat member is used.
