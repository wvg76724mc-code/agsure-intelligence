# AgSure Intelligence

AgSure Intelligence is a transparent, source-traceable agricultural market
intelligence project. Version 0.8 tracks five Prairie crops and adds a separate
official ECCC daily station-weather vertical:

- Barley
- Canola
- Spring wheat
- Durum wheat
- Dry peas

Barley is the first fully implemented analytical vertical. It asks:

> Is the Southern Alberta barley supply outlook becoming tighter or more
> abundant than its recent historical baseline?

The dashboard opens on a unified official commodity overview and adds an
official weekly regional crop-conditions slice while retaining
the synthetic demonstration and every detailed production, stocks,
supply-and-disposition, and stocks-to-use view. Official observations and
calculations are displayed for monitoring only; they are not forecasts, trading
signals, recommendations, or validated predictors.

## What works now

- Ingests official ECCC GeoMet daily maximum, minimum, mean, and total
  precipitation for five exact Southern Alberta Climate IDs from 2024-01-01
  through a runtime-selected completed day, including current-year-to-date
  coverage. Every value remains station-specific; no regional
  observation, average, interpolation, successor splice, or town-level claim is
  created.
- Calculates separate daily growing degree days with Decimal arithmetic from
  same-station, same-date, unflagged official maximum and minimum temperatures
  using the documented v0.8 base-5°C convention. Missing or flagged inputs make
  GDD unavailable; cumulative GDD is deferred.
- Publishes weather source responses, retrieval sidecars, processed rows, and
  manifests as weather-only immutable generations behind `weather.CURRENT`.
  The dedicated dashboard requires station and period selection; the compact
  overview requires station and date selection.

- Ingests embedded PDF text from representative 2026 Alberta and Saskatchewan
  official crop reports into a separate normalized long-form artifact with
  document SHA-256, release/retrieval dates, exact crop and region labels,
  status, raw value, page/table provenance, extraction method, and parser
  version. OCR is not used.
- Retains Alberta's exact published `Per Cent Rated Good-to-Excellent
  Conditions` for barley, canola, spring wheat, durum, and dry peas at the
  provincial level and in South, Central, N East, N West, and Peace wherever
  the source publishes a value.
- Retains Saskatchewan's exact `excellent`, `good`, `fair`, `poor`, and `very
  poor` crop-condition distributions for barley, canola, spring wheat, durum,
  and the distinct regional identity `field-peas`, preserving the source term
  `Field Pea`, at provincial and six official regions. It is never joined to
  Statistics Canada's `dry-peas` identity.
- Validates Manitoba's current title, publisher, commodity, and five regional
  section contracts but reports numeric crop conditions unavailable because
  the current regional content is narrative. Narrative is never converted to
  a number.
- Adds a detailed official regional view and a gated compact overview section.
  A province and its exact official region must be selected; no Prairie average
  or regional condition score is calculated.

- Presents the available official production, stocks, supply-and-disposition,
  and stocks-to-use histories together for one commodity, with latest values,
  exact periods, units, geography, source links, releases, retrieval vintages,
  and expandable row provenance.
- Applies the geography selector only to production and stocks. Canada-only
  supply-and-disposition and stocks-to-use values remain labelled Canada and
  never inherit a selected province.
- Shows explicit unavailable states. Spring wheat is populated from its exact
  production member only; aggregate wheat members are never substituted for
  absent stocks, supply-and-disposition, or stocks-to-use series.

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

For official crop-report PDF ingestion, install the separate PDF extra and run:

```bash
python -m pip install -e ".[crop-conditions]"
PYTHONPATH=src python -m agsure.crop_conditions.ingest
```

For official ECCC daily station weather:

```bash
# Refresh through the latest eligible completed day:
PYTHONPATH=src python -m agsure.weather.ingest --to-latest
# The installed console command is equivalent:
agsure-weather --to-latest
# Deterministic replay/testing (ends at 2026-07-20):
agsure-weather --to-latest --as-of-date 2026-07-21
# Explicit bounded historical retrieval:
agsure-weather --start-date 2025-06-01 --end-date 2025-06-30 --force
```

`--to-latest` starts at 2024-01-01 unless `--start-date` is supplied. Its end is
the calendar day immediately before the runtime as-of date in the explicit
`America/Edmonton` timezone. It never requests the current local date, even if
ECCC has already created a blank row. An explicit retrieval requires
`--end-date`; `--as-of-date` requires `--to-latest`; and `--to-latest` cannot be
combined with `--end-date`. Longer ranges are split into independently retained
requests of at most 731 days. Missing source dates remain explicit unavailable
rows through the requested coverage end; station publication lag never silently
shortens the artifact.

Every `--to-latest` run fetches a fresh official vintage. A successful rerun
publishes a new immutable generation even when every source hash is unchanged.
Later ECCC changes therefore become a separate revision vintage, while the old
generation remains readable. Any download, schema, validation, manifest, hash,
or pre-publication integrity failure leaves `weather.CURRENT` unchanged.
Raw GeoJSON, retrieval metadata, immutable generations, and processed artifacts
remain Git-ignored. Offline tests use clearly synthetic source-shaped fixtures.

There is no hosted scheduler in this repository. A local daily cron entry can
run the installed command after local midnight (the command's date rule remains
timezone-independent of the host):

```cron
17 7 * * * cd /absolute/path/to/agsure-intelligence && .venv/bin/agsure-weather --to-latest
```

For a weekly refresh, replace the schedule with `17 7 * * 1`. A hosted job must
retain both `data/raw/weather/generations/` and
`data/processed/weather.CURRENT` at stable relative paths between runs. The
generation directory contains the raw responses, retrieval sidecars, processed
artifact, manifests, URLs, timestamps, and hashes; ephemeral storage would
destroy the immutable-vintage contract. No credentials are required or stored
by this connector. Because unchanged reruns are retained, the operator must
monitor capacity and apply an explicit, audited retention policy if needed.

Raw PDFs, retrieval sidecars, processed CSVs, and manifests are written into an
immutable directory under `data/raw/crop_conditions/generations/`. The logical
processed path remains `data/processed/crop_conditions.csv`; readers resolve
its adjacent `crop_conditions.CURRENT` regular-file pointer once and read both
processed files from that generation. Ingestion replaces CURRENT only after all
three provinces and processed outputs are validated, hashed, flushed, and
fsynced. Prior generations remain available after interruption. The adapters
fail closed and do not invoke OCR.

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
`data/processed/statcan_stocks_to_use.csv`. All generated processed CSVs remain
local and Git-ignored. The overview reads these artifacts and never triggers
ingestion or a download. For fixture or deployment testing,
`AGSURE_PROCESSED_DIR` may point the dashboard at another directory containing
the four standard processed filenames.

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
cumulative over that crop year. Version 0.5 introduced the July-only calculation
retained by v0.7:
`Total ending stocks / (Total exports + Total domestic disappearance) * 100`.
`Total disposition` is not the denominator because it includes ending stocks.
The current cube has no spring-wheat-specific supply-and-disposition member;
AgSure does not map `All wheat` or `Wheat, excluding durum` to spring wheat.
Regional crop-report observations remain separate from annual Statistics
Canada production and Canada-level supply/disposition. Province region systems
are not interchangeable, `Field Pea` is not asserted to be definitionally
identical to Statistics Canada's `Peas, dry`, and weekly conditions are not
claimed to predict yield, production, prices, bids, or stocks-to-use. Weather
forecasts, regional weather estimates, bids, prices, price forecasts, and a
real-data supply-pressure score remain out of scope. Official station weather
and calculated daily GDD are display-only and never enter the existing
synthetic barley score.

The v0.7 overview retains the greatest-source-period selection for each exact
series identity. If that newest source row is unpublished or cannot be
calculated, the value is unavailable; an older published row is not silently
substituted. Stocks histories contain one exact stock type and snapshot period.
Supply-and-disposition histories contain one exact measure and snapshot period.
Stocks-to-use remains Canada-level, July-only, and restricted to completed
August–July crop years.

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
