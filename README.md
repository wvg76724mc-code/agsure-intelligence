# AgSure Intelligence

AgSure Intelligence is a transparent, source-traceable agricultural market
intelligence project. Version 0.5 tracks five Prairie crops:

- Barley
- Canola
- Spring wheat
- Durum wheat
- Dry peas

Barley is the first fully implemented analytical vertical. It asks:

> Is the Southern Alberta barley supply outlook becoming tighter or more
> abundant than its recent historical baseline?

The dashboard can show synthetic demonstration history, official Statistics
Canada production data, crop stocks, or a narrow Canada-level
supply-and-disposition monitoring slice, or completed-crop-year official
stocks-to-use ratios. Official observations and calculations are displayed for
monitoring only; they are not forecasts, trading signals, recommendations, or
validated predictors.

## What works now

- Loads a normalized multi-commodity annual dataset.
- Calculates five-year baselines and current deviations.
- Calculates stocks-to-use in the synthetic demonstration model without
  changing that model's established result.
- Produces a transparent 0-100 barley supply-pressure indicator.
- Reports every component and weight used in the indicator.
- Includes a PostgreSQL/PostGIS schema for source and revision tracking.
- Includes automated tests and a small Streamlit dashboard.
- Downloads and caches Statistics Canada table 32-10-0359-01.
- Normalizes seeded area, harvested area, yield, and production for Canada and
  the three Prairie provinces while retaining row-level provenance.
- Keeps official-source production observations separate from the synthetic
  inputs required by the supply-pressure demonstration score.
- Downloads and normalizes Statistics Canada table 32-10-0007-01 for barley,
  canola, durum wheat, and dry peas.
- Compares March 31, July 31, and December 31 stocks only with the same snapshot
  in other years, including strict year-over-year and five-year comparisons.
- Preserves total, farm, and commercial stock labels where the source publishes
  them. Provincial rows in this table provide farm stocks; Canada provides all
  three types.
- Downloads and normalizes Statistics Canada table 32-10-0013-01 for the exact
  `Barley`, `Canola`, `Durum wheat`, and `Dry peas` members at Canada level.
- Preserves every exact supply-and-disposition measure published for those
  members, with raw values, units, scalars, source status fields, vector,
  coordinate, DGUID, release date, and retrieval time kept separately from
  normalized tonnes.
- Compares only the same measure and March, July, or December reporting snapshot
  across crop years. It never adds snapshots or feeds these observations into
  the existing supply-pressure score.
- Rebuilds a separate official historical stocks-to-use CSV from exact Canada,
  July, crop-year, and normalized-tonne matches for `Total ending stocks`,
  `Total exports`, and `Total domestic disappearance`.
- Preserves all three source rows and optionally reconciles their sum against
  `Total disposition`; a documented source-rounding difference never silently
  changes a published value.

## Quick start

The calculation engine uses only the Python standard library:

```bash
PYTHONPATH=src python -m agsure.cli --input sample_data/crops_synthetic.csv --commodity barley
python -m unittest discover -s tests -v
```

For the dashboard:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dashboard]"
streamlit run src/agsure/dashboard.py
```

To download the full official table and write the dashboard-ready processed
CSV (the raw and processed data directories are intentionally ignored by Git):

```bash
PYTHONPATH=src python -m agsure.statcan
PYTHONPATH=src python -m agsure.statcan_stocks
PYTHONPATH=src python -m agsure.statcan_supply_disposition
PYTHONPATH=src python -m agsure.stocks_to_use
```

The command reuses a cached ZIP after verifying its SHA-256 digest. Pass
`--force` only when intentionally retrieving a new release. The processed file
is written to `data/processed/statcan_crop_production.csv` by default. Download
and parsing use the Python standard library. The stocks command writes
`data/processed/statcan_crop_stocks.csv` and uses the same verified cache and
provenance pattern. The supply-and-disposition command writes
`data/processed/statcan_supply_disposition.csv`. The stocks-to-use command uses
that existing normalized file without downloading anything and writes
`data/processed/statcan_stocks_to_use.csv`. Both generated CSVs remain local and
Git-ignored.

For PostgreSQL/PostGIS:

```bash
cp .env.example .env
docker compose up -d db
```

## Indicator interpretation

Higher scores indicate greater modelled supply pressure relative to the
trailing five-year baseline:

- 0-29: tight
- 30-44: moderately tight
- 45-55: balanced
- 56-70: moderately abundant
- 71-100: abundant

This barley model is initially a documented heuristic, not a validated price forecast. See
[`docs/methodology.md`](docs/methodology.md).

## Data sources

Statistics Canada tables 32-10-0359-01, 32-10-0007-01, and 32-10-0013-01 are
implemented official-source connectors. Table 32-10-0013-01 says the selected
crops use an August–July crop year and its March, July, and December periods are
cumulative over that crop year. Version 0.5 uses July only to calculate:
`Total ending stocks / (Total exports + Total domestic disappearance) * 100`.
`Total disposition` is not the denominator because it includes ending stocks.
The current cube has no spring-wheat-specific supply-and-disposition member;
AgSure does not map `All wheat` or `Wheat, excluding durum` to spring wheat.
Weather, bids, prices, price forecasts, and a real-data supply-pressure score
remain out of scope.

The initial approved Statistics Canada tables and ingestion requirements are
listed in [`docs/data-sources.md`](docs/data-sources.md).

## Project status

**Pre-alpha / portfolio foundation.** Source type and observation status remain
prominent so official-source estimates cannot be confused with synthetic model
inputs or commercial market advice.

## Copyright

Copyright © 2026 Roman Irodenko. All rights reserved. This repository is
publicly viewable but is not distributed under an open-source licence. See
[`COPYRIGHT`](COPYRIGHT).
