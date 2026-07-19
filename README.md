# AgSure Intelligence

AgSure Intelligence is a transparent, source-traceable agricultural market
intelligence project. Version 0.1 tracks five Prairie crops:

- Barley
- Canola
- Spring wheat
- Durum wheat
- Dry peas

Barley is the first fully implemented analytical vertical. It asks:

> Is the Southern Alberta barley supply outlook becoming tighter or more
> abundant than its recent historical baseline?

This first checkpoint proves the calculation and data architecture using
**synthetic demonstration data only**. It does not yet publish a real crop
forecast or trading recommendation.

## What works now

- Loads a normalized multi-commodity annual dataset.
- Calculates five-year baselines and current deviations.
- Calculates stocks-to-use.
- Produces a transparent 0-100 barley supply-pressure indicator.
- Reports every component and weight used in the indicator.
- Includes a PostgreSQL/PostGIS schema for source and revision tracking.
- Includes automated tests and a small Streamlit dashboard.

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

## Planned live sources

1. Statistics Canada crop area, yield, production, and stocks.
2. Agriculture and Agri-Food Canada supply and disposition.
3. Environment and Climate Change Canada daily weather observations.
4. AAFC Annual Crop Inventory spatial classifications.
5. USDA NASS comparison data after the Canadian pipeline is stable.

The initial approved Statistics Canada tables and ingestion requirements are
listed in [`docs/data-sources.md`](docs/data-sources.md).

## Project status

**Pre-alpha / portfolio foundation.** Synthetic data is deliberately prominent
so nobody can mistake this checkpoint for commercial market advice.

## Copyright

Copyright © 2026 Roman Irodenko. All rights reserved. This repository is
publicly viewable but is not distributed under an open-source licence. See
[`COPYRIGHT`](COPYRIGHT).
