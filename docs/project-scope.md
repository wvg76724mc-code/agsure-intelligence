# AgSure Intelligence v0.3 scope

## Decision question

How are acreage, yield, production, and stocks changing across five principal
Prairie crops, and is Southern Alberta barley supply becoming tighter or more
abundant than its recent five-year baseline?

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

## Excluded from v0.3

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

## Completion criteria

A new contributor can reproduce the calculation, inspect every component,
identify whether each value is synthetic or sourced, and run all tests from a
fresh checkout.
