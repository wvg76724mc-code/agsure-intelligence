from __future__ import annotations

import argparse
from pathlib import Path

from agsure.analysis import calculate_supply_pressure
from agsure.commodities import COMMODITIES
from agsure.io import load_observations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Calculate the AgSure barley supply-pressure demonstration score."
    )
    parser.add_argument("--input", type=Path, required=True, help="Input CSV file")
    parser.add_argument(
        "--commodity", choices=tuple(COMMODITIES), default="barley"
    )
    parser.add_argument("--baseline-years", type=int, default=5)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    observations = [
        item for item in load_observations(args.input) if item.commodity == args.commodity
    ]
    if not observations:
        raise SystemExit(f"No observations found for commodity {args.commodity!r}")
    result = calculate_supply_pressure(observations, args.baseline_years)

    commodity = COMMODITIES[args.commodity]
    print(f"AgSure Intelligence — {commodity.display_name} Supply Pressure")
    print(f"Crop year: {result.crop_year}")
    print(f"Observation status: {result.observation_status.upper()}")
    print(f"Score: {result.score}/100 ({result.classification})")
    print("Components:")
    for component in result.components:
        print(
            f"  {component.name}: deviation={component.deviation_pct:.1f}% "
            f"weight={component.weight:.0%} contribution={component.contribution:.1f}"
        )

    if result.observation_status == "synthetic":
        print("WARNING: Synthetic demonstration data; not a market forecast.")


if __name__ == "__main__":
    main()
