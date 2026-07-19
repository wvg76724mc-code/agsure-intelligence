# AgSure repository guidance

AgSure Intelligence is an agricultural market-intelligence project. Accuracy,
traceability, and reproducibility take priority over visual polish or feature
count.

## Permanent rules

- Never invent, interpolate, or silently repair a missing observation.
- Preserve raw source values separately from transformed values.
- Every non-synthetic observation must retain its publisher, source URL,
  release date, reference period, unit, geography, and observation status.
- Keep official, estimated, forecast, modelled, and synthetic values distinct.
- Use metric units internally. Conversions must be explicit and tested.
- Calculations affecting market interpretation require automated tests.
- Composite indicators must expose their components and weights.
- Never commit credentials, confidential bids, contracts, or producer data.
- Do not commit large raw government or geospatial downloads to Git.
- Keep changes scoped and document material methodology changes.
- Do not describe a model output as a recommendation to buy, sell, bid, or
  contract grain.

## Verification

Run before committing:

```bash
python -m unittest discover -s tests -v
python -m agsure.cli --input sample_data/crops_synthetic.csv --commodity barley
```
