from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from agsure.analysis import calculate_supply_pressure
from agsure.commodities import COMMODITIES
from agsure.io import load_observations


ROOT = Path(__file__).parents[2]
SYNTHETIC_PATH = ROOT / "sample_data" / "crops_synthetic.csv"
STATCAN_PATH = ROOT / "data" / "processed" / "statcan_crop_production.csv"
METRIC_LABELS = {
    "seeded-area": "Seeded area",
    "harvested-area": "Harvested area",
    "yield": "Yield",
    "production": "Production",
}


def show_synthetic() -> None:
    st.error(
        "Synthetic demonstration data — not a crop forecast or trading "
        "recommendation."
    )
    frame = pd.read_csv(SYNTHETIC_PATH)
    selected_slug = st.selectbox(
        "Commodity",
        options=list(COMMODITIES),
        format_func=lambda slug: COMMODITIES[slug].display_name,
    )
    commodity = COMMODITIES[selected_slug]
    observations = [
        item
        for item in load_observations(SYNTHETIC_PATH)
        if item.commodity == selected_slug
    ]
    selected_frame = frame[frame["commodity"] == selected_slug]

    if commodity.score_model_enabled:
        result = calculate_supply_pressure(observations)
        left, middle, right = st.columns(3)
        left.metric("Crop year", result.crop_year)
        middle.metric("Supply-pressure score", f"{result.score}/100")
        right.metric("Classification", result.classification.title())
    else:
        result = None
        st.info(
            f"Historical monitoring is enabled for {commodity.display_name}; its "
            "crop-specific supply-pressure model is not yet validated."
        )

    st.caption(
        "Source: AgSure synthetic demonstration dataset · Geography: illustrative"
    )
    st.subheader("Production history")
    figure = px.line(
        selected_frame,
        x="crop_year",
        y="production_kt",
        markers=True,
        labels={"crop_year": "Crop year", "production_kt": "Production (kt)"},
    )
    st.plotly_chart(figure, width="stretch")

    if result is not None:
        st.subheader("Score components")
        components = pd.DataFrame(
            [
                {
                    "component": item.name.replace("_", " ").title(),
                    "current": float(item.current),
                    "baseline": float(item.baseline),
                    "deviation_pct": float(item.deviation_pct),
                    "weight_pct": float(item.weight * 100),
                    "score_contribution": float(item.contribution),
                }
                for item in result.components
            ]
        )
        st.dataframe(components, hide_index=True, width="stretch")


def show_statcan() -> None:
    st.info(
        "Official Statistics Canada source. Published observations in this table "
        "are estimates and may be revised."
    )
    if not STATCAN_PATH.exists():
        st.warning(
            "The processed Statistics Canada cache is not available. Run "
            "`PYTHONPATH=src python -m agsure.statcan` and reload the dashboard."
        )
        return

    frame = pd.read_csv(STATCAN_PATH, dtype=str, keep_default_na=False)
    selected_slug = st.selectbox(
        "Commodity",
        options=list(COMMODITIES),
        format_func=lambda slug: COMMODITIES[slug].display_name,
    )
    geography = st.selectbox(
        "Geography", options=["Canada", "Alberta", "Saskatchewan", "Manitoba"]
    )
    metric = st.selectbox(
        "Metric",
        options=list(METRIC_LABELS),
        format_func=lambda slug: METRIC_LABELS[slug],
        index=3,
    )
    selected = frame[
        (frame["commodity"] == selected_slug)
        & (frame["geography"] == geography)
        & (frame["metric"] == metric)
    ].copy()
    selected["value_numeric"] = pd.to_numeric(selected["value"], errors="coerce")
    chart_frame = selected.dropna(subset=["value_numeric"]).sort_values(
        "reference_period"
    )
    if chart_frame.empty:
        st.warning("No published values match this commodity, geography, and metric.")
        return

    latest = chart_frame.iloc[-1]
    revision_marker = latest["symbol"] if latest["symbol"] == "r" else "none"
    status_marker = latest["status_marker"] or "none"
    first, second, third, fourth = st.columns(4)
    first.metric("Source", latest["source_table"])
    second.metric("Geography", geography)
    third.metric("Metric", METRIC_LABELS[metric])
    fourth.metric("Latest observation", latest["reference_period"])
    st.caption(
        f"Publisher: {latest['publisher']} · "
        f"Status: {latest['observation_status']} · "
        f"Status marker: {status_marker} · Revision marker: {revision_marker} · "
        f"Release: {latest['release_date']} · "
        f"Retrieved: {latest['retrieved_at']}"
    )

    unit = latest["unit"]
    st.subheader(f"{METRIC_LABELS[metric]} history")
    figure = px.line(
        chart_frame,
        x="reference_period",
        y="value_numeric",
        markers=True,
        labels={
            "reference_period": "Reference period",
            "value_numeric": f"{METRIC_LABELS[metric]} ({unit})",
        },
    )
    st.plotly_chart(figure, width="stretch")
    st.warning(
        "No supply-pressure score is calculated from this dataset. Carryout, total "
        "use, precipitation, and growing-degree-day inputs are not present."
    )
    with st.expander("Latest observation provenance"):
        st.dataframe(
            latest[
                [
                    "source_crop",
                    "source_value",
                    "source_unit",
                    "scalar_factor",
                    "value",
                    "unit",
                    "status_marker",
                    "vector",
                    "coordinate",
                    "dguid",
                    "symbol",
                    "terminated",
                ]
            ].to_frame("value"),
            width="stretch",
        )


st.set_page_config(page_title="AgSure Intelligence", page_icon="🌾", layout="wide")
st.title("AgSure Intelligence")
source = st.selectbox(
    "Data source",
    options=("synthetic", "statcan"),
    format_func=lambda value: {
        "synthetic": "Synthetic demonstration data",
        "statcan": "Official Statistics Canada crop production",
    }[value],
)

if source == "synthetic":
    show_synthetic()
else:
    show_statcan()

with st.expander("Methodology and limitations"):
    st.markdown((ROOT / "docs" / "methodology.md").read_text(encoding="utf-8"))
