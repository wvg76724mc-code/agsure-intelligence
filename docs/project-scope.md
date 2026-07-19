# AgSure Intelligence v0.5 scope

## Decision question

What were the transparent historical stocks-to-use ratios for barley, canola,
durum wheat, and dry peas in completed Canada-level August–July crop years,
while preserving all earlier official and synthetic views?

## Included

- Barley, canola, spring wheat, durum wheat, and dry peas in the shared data
  pipeline and historical dashboard.
- Barley only for the initial supply-pressure model.
- Alberta as the initial official statistical geography.
- Southern Alberta as the eventual weather and crop-inventory study area.
- Annual acreage, yield, production, stocks, use, precipitation, and
  growing-degree-day inputs.
- Point-in-time source and revision metadata.
- A transparent supply-pressure heuristic.
- A separate Canada-only Statistics Canada supply-and-disposition view for the
  exact `Barley`, `Canola`, `Durum wheat`, and `Dry peas` series.
- Exact source measures and March, July, and December same-period comparisons.
- Explicit August–July crop-year and cumulative reporting-period semantics.
- A separate July-only official stocks-to-use calculation using exact ending
  stocks, exports, and domestic disappearance measures in normalized tonnes.
- Input-level provenance, explicit unavailability, balance reconciliation, and
  strict consecutive-year dashboard comparisons.

## Excluded from v0.5

- Cash-bid recommendations.
- Futures or automated trading.
- Contracts, payments, escrow, or blockchain.
- Producer accounts or confidential data.
- Machine-learning yield forecasts.
- Claims at town-level precision unsupported by official data.
- Applying the barley model weights to other crops without validation.
- Spring-wheat-specific stocks or treating wheat excluding durum as spring wheat.
- Total use, stocks-to-use, weather, buyer bids, or price forecasts in the
  official stocks vertical slice.
- PostgreSQL changes, deployment, town-level analysis, and visual redesign.
- Adding supply-and-disposition observations to, or modifying, the existing
  synthetic barley supply-pressure score.
- Combining March, July, and December snapshots or treating repeated crop-year
  components as additive observations.
- Relabelling July `Total ending stocks` as carryout.
- Using `Total disposition` as total use or silently forcing a source balance.
- A real-data supply-pressure score, weather, cash bids, prices, price
  forecasting, provincial or town-level ratios, PostgreSQL changes, deployment,
  visual redesign, or AI-generated narrative.

## Completion criteria

A new contributor can reproduce the calculation, inspect every component,
identify whether each value is synthetic or sourced, and run all tests from a
fresh checkout.
