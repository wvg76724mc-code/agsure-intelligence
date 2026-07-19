# Methodology

## Purpose

The initial barley supply-pressure score is a transparent engineering heuristic. It
exists to test the data pipeline and reporting pattern before sufficient real
history is available for validation.

The shared ingestion and dashboard layer covers five crops, but the score is
enabled only for barley. Canola, spring wheat, durum wheat, and dry peas require
separate component selection, weights, and backtesting before model scores are
published.

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

Before commercial use, weights must be backtested against out-of-sample
production and basis outcomes with documented error metrics.
