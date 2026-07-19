# Approved data-source registry

Only official, licensed, and documented sources may feed production indicators.
This registry records the first planned connectors; it is not evidence that a
connector has already been implemented.

## Statistics Canada

### Principal field-crop area, yield, and production

- Publisher: Statistics Canada
- Product ID: `32100359`
- Table: `32-10-0359-01`
- Frequency: Annual
- Initial use: seeded area, harvested area, yield, and production for barley,
  canola, spring wheat, durum wheat, and dry peas
- Full-table CSV pattern:
  `https://www150.statcan.gc.ca/n1/en/tbl/csv/32100359-eng.zip`

### Principal field-crop stocks

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
