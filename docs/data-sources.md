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

Status: **planned; not ingested in v0.2**

- Publisher: Statistics Canada
- Product ID: `32100007`
- Table: `32-10-0007-01`
- Initial use: crop stocks by reporting date and geography where the table's
  commodity detail supports the requested series
- Full-table CSV pattern:
  `https://www150.statcan.gc.ca/n1/en/tbl/csv/32100007-eng.zip`

## Ingestion requirements

- Store the downloaded file's SHA-256 digest.
- Retain the release and retrieval dates.
- Store revision markers instead of stripping them.
- Keep the raw download outside Git.
- Never combine stocks from different reporting dates without an explicit
  transformation.
- Add a fixture-based parser test before loading observations into PostgreSQL.

## v0.2 cache and transformation

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
