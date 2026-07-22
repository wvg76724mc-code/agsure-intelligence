# AgSure Intelligence v0.8 scope

## Decision question

What station-specific historical weather context can official ECCC daily
observations support without weakening the identities and guardrails
established in v0.2–v0.7?

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
- A unified overview as the default dashboard source with latest snapshot,
  production, stocks, supply-and-disposition, stocks-to-use, and availability
  and provenance sections.
- A testable, Streamlit-free service/view-model using existing local processed
  artifacts, `Decimal` values, deterministic latest selection, and explicit
  duplicate, source, geography, unit, crop, and period validation.
- Province controls for geographically appropriate production and stocks only;
  Canada-only values stay visibly Canada-level.
- Explicit unavailable sections rather than proxy series or older-value
  substitution, including spring-wheat limitations.
- A separate official regional crop-conditions artifact and separate province
  adapters using embedded PDF text only.
- Alberta exact crop-by-region combined good-to-excellent observations and
  Saskatchewan exact crop-by-region five-category distributions for five exact
  source crops. Saskatchewan `Field Pea` uses a distinct regional identity and
  is not equated with Statistics Canada `dry-peas`.
- Manitoba current-format and official-region validation with explicit numeric
  unavailability because the representative regional content is narrative.
- A detailed crop-conditions view and a compact unified-overview section that
  requires province and exact official-region selection.
- One representative July 2026 report per province; history completeness is
  explicitly narrow and tested as such.
- A separate official ECCC daily-weather vertical for the exact configured
  Claresholm, Lethbridge, Brooks, Bow Island, and Medicine Hat RCS Climate IDs.
- Official daily maximum, minimum, mean when published, and total precipitation
  for the bounded 2024–2025 period, with explicit source gaps and flags.
- Separate Decimal-safe daily GDD using the documented 5°C v0.8 convention,
  exact maximum/minimum input keys, and no cumulative series.
- Weather-only immutable generations and `weather.CURRENT`, a dedicated
  station/date-gated dashboard, and a compact station/date-gated overview.

## Excluded from v0.8

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
- New official-source downloads solely for overview rendering, ingestion-module
  consolidation, deletion of specialist views, or broad dashboard restyling.
- Crop weather tables, satellite imagery, NDVI, remote sensing, soil-moisture
  models, yield or price forecasting, cash bids,
  town-level estimates, producer observations, automated email reports, and
  AI-generated crop summaries.
- Cross-province category comparisons, Prairie averages or condition scores,
  regional-to-provincial aggregation, and any change to the synthetic
  72.1/100 result.
- Forecasts, weather recommendations, drought/moisture/weather scores, regional
  weather estimates, interpolation, station averaging, successor splicing,
  cumulative GDD, weather-to-price models, and weather inputs to the synthetic
  supply-pressure score.

## Completion criteria

A new contributor can reproduce the calculation, inspect every component,
identify whether each value is synthetic or sourced, and run all tests from a
fresh checkout.
