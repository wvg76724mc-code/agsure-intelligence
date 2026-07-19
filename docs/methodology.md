# Methodology

## Purpose

The initial barley supply-pressure score is a transparent engineering heuristic. It
exists to test the data pipeline and reporting pattern before sufficient real
history is available for validation.

The shared ingestion and dashboard layer covers five crops, but the score is
enabled only for barley. Canola, spring wheat, durum wheat, and dry peas require
separate component selection, weights, and backtesting before model scores are
published.

The production Statistics Canada slice supplies area, yield, and production. It
does not supply carry-out stocks, total use, precipitation, or growing-degree
days. Consequently, official-source rows are never adapted into
`CropYearObservation` objects and never produce the barley supply-pressure
score. The dashboard calculates that demonstration score only after the user
selects the complete synthetic dataset.

## Official crop-stocks monitoring

Version 0.3 adds a separate descriptive view of table 32-10-0007-01. For a
selected commodity, geography, and exact source stock type, the view filters to
one snapshot period before calculating or charting anything. March 31 is
therefore compared only with March 31, July 31 only with July 31, and December
31 only with December 31.

Year-over-year change uses the immediately preceding year's same-period value.
The five-year average uses the five immediately preceding same-period values
and excludes the current value. If any required observation is blank, the
corresponding comparison is unavailable; an older value is never substituted.
Deviation is `(latest - five-year average) / five-year average * 100`. A zero
comparison value produces no percentage rather than an infinite or invented
result.

These comparisons describe published stock estimates. They are not price
forecasts and are not recommendations to buy, sell, bid, or contract grain.
They do not calculate total use, stocks-to-use, or the supply-pressure score.
Spring-wheat-specific stocks are unavailable from this table, and “wheat
excluding durum” is not used as a proxy.

## Official supply-and-disposition monitoring

Version 0.4 adds a distinct descriptive view of table 32-10-0013-01 for Canada.
It keeps the source's exact crop and measure labels and filters to one commodity,
one measure, and one March, July, or December snapshot before calculating or
charting anything. Year-over-year change, the five-year average, and deviation
use the same strict consecutive same-period rules as the v0.3 stocks view. A
missing required observation makes the affected comparison unavailable; it is
never interpolated or replaced with an older value.

Statistics Canada source note 2 says the selected grains use an August–July
crop year. March means August through March, July means August through July,
and December means August through December. Flow measures such as exports and
domestic disappearance are therefore cumulative crop-year-to-date at each
snapshot. March, July, and December values must not be added together.
Production and beginning stocks can repeat across snapshots because they are
components of the same crop-year account; repeated values are not counted as
new production or stocks. AgSure retains the exact `Total ending stocks` label
and does not relabel July ending stocks as “carryout.”

The dashboard displays normalized tonnes while exposing the original value,
unit, scalar, status fields, vector, coordinate, DGUID, crop-year relationship,
release, retrieval time, and source URLs. Historical rows downloaded from the
current full cube are the latest revised vintage, not observations preserved as
they appeared on their original release dates.

The view does not calculate stocks-to-use and does not calculate, modify, or
otherwise consume the synthetic barley supply-pressure score. Its comparisons
are not price forecasts and are not recommendations to buy, sell, bid, or
contract grain. Spring-wheat-specific supply-and-disposition data are
unavailable from this cube; neither `All wheat` nor `Wheat, excluding durum` is
used as a proxy.

## Baseline

The latest crop year is compared with the five immediately preceding crop
years. The baseline excludes the current year.

## Components

Each component is expressed as a percentage deviation from its baseline:

| Component | Weight |
|---|---:|
| Production | 40% |
| Carry-out stocks | 25% |
| Stocks-to-use | 20% |
| Precipitation versus normal | 10% |
| Growing-degree days versus normal | 5% |

The weather inputs are already expressed relative to normal, so their
deviations are calculated as `value - 100`.

```text
score = 50
      + 0.40 * production deviation
      + 0.25 * carry-out deviation
      + 0.20 * stocks-to-use deviation
      + 0.10 * precipitation deviation from normal
      + 0.05 * growing-degree-day deviation from normal
```

The result is bounded to 0-100. A higher value represents more abundant supply
pressure. It does not directly predict price or basis.

## Known limitations

- Component weights have not been econometrically estimated.
- Weather relationships vary by crop stage and location.
- Provincial statistics do not establish town-level production.
- Local demand, quality, freight, competition, and buyer inventory are absent.
- Synthetic sample data cannot be used to assess predictive accuracy.
- Statistics Canada estimates may be revised, and historical rows in a current
  full-table download reflect the latest published vintage rather than a
  point-in-time vintage archive.
- Provincial rows for the selected crops contain farm stocks, while commercial
  and total stocks are published at Canada level in this table.
- From March 2023, Statistics Canada notes that farm stocks for several
  provinces and crops use modelled inputs; row-level statuses and source notes
  should be consulted when interpreting the series.
- Supply-and-disposition history is a latest-revised current-cube vintage, not
  a point-in-time revision archive.
- Supply-and-disposition subcomponents differ by crop; absent exact source
  measures are not inferred from totals or residuals.
- The current cube reports literal zero values for dry-pea production and
  beginning-stock components at the December 1998 and March 1999 snapshots,
  followed by nonzero July 1999 values for the same 1998/1999 crop year. AgSure
  preserves these source observations and does not repair or reinterpret them.

Before commercial use, weights must be backtested against out-of-sample
production and basis outcomes with documented error metrics.
