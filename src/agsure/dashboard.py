from decimal import Decimal
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from agsure.analysis import calculate_supply_pressure
from agsure.commodities import COMMODITIES
from agsure.io import load_observations
from agsure.stocks import compare_same_snapshot
from agsure.statcan_supply_disposition import MEASURES as SUPPLY_DISPOSITION_MEASURES


ROOT = Path(__file__).parents[2]
SYNTHETIC_PATH = ROOT / "sample_data" / "crops_synthetic.csv"
STATCAN_PRODUCTION_PATH = (
    ROOT / "data" / "processed" / "statcan_crop_production.csv"
)
STATCAN_STOCKS_PATH = ROOT / "data" / "processed" / "statcan_crop_stocks.csv"
STATCAN_SUPPLY_DISPOSITION_PATH = (
    ROOT / "data" / "processed" / "statcan_supply_disposition.csv"
)
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


def show_statcan_production() -> None:
    st.info(
        "Official Statistics Canada source. Published observations in this table "
        "are estimates and may be revised."
    )
    if not STATCAN_PRODUCTION_PATH.exists():
        st.warning(
            "The processed Statistics Canada cache is not available. Run "
            "`PYTHONPATH=src python -m agsure.statcan` and reload the dashboard."
        )
        return

    frame = pd.read_csv(
        STATCAN_PRODUCTION_PATH, dtype=str, keep_default_na=False
    )
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


def _format_pct(value: Decimal | None) -> str:
    return "Not available" if value is None else f"{value:+.1f}%"


def show_statcan_stocks() -> None:
    st.info(
        "Official Statistics Canada stock estimates. Comparisons are descriptive "
        "and are not price forecasts or recommendations."
    )
    if not STATCAN_STOCKS_PATH.exists():
        st.warning(
            "The processed Statistics Canada stocks cache is not available. Run "
            "`PYTHONPATH=src python -m agsure.statcan_stocks` and reload the "
            "dashboard."
        )
        return

    frame = pd.read_csv(STATCAN_STOCKS_PATH, dtype=str, keep_default_na=False)
    commodity_options = list(dict.fromkeys(frame["commodity"]))
    selected_slug = st.selectbox(
        "Commodity",
        options=commodity_options,
        format_func=lambda slug: COMMODITIES[slug].display_name,
    )
    geography = st.selectbox(
        "Geography",
        options=[
            item
            for item in ("Canada", "Alberta", "Saskatchewan", "Manitoba")
            if item in set(frame["geography"])
        ],
    )
    available_stock_types = list(
        dict.fromkeys(
            frame.loc[frame["geography"] == geography, "stock_type"].tolist()
        )
    )
    stock_type = st.selectbox("Stock type", options=available_stock_types)
    snapshot_options = [
        item
        for item in ("March 31", "July 31", "December 31")
        if item in set(frame["snapshot_period"])
    ]
    snapshot_period = st.selectbox("Snapshot period", options=snapshot_options)

    selected = frame[
        (frame["commodity"] == selected_slug)
        & (frame["geography"] == geography)
        & (frame["stock_type"] == stock_type)
        & (frame["snapshot_period"] == snapshot_period)
    ].copy()
    if selected.empty:
        st.warning("No source rows match the selected stock series.")
        return

    observations = {
        row["reference_period"]: (
            Decimal(row["normalized_tonnes"])
            if row["normalized_tonnes"]
            else None
        )
        for _, row in selected.iterrows()
    }
    try:
        comparison = compare_same_snapshot(observations)
    except ValueError as exc:
        st.warning(str(exc))
        return

    latest = selected[
        selected["reference_period"] == comparison.reference_period
    ].iloc[0]
    first, second, third, fourth = st.columns(4)
    first.metric("Latest stocks", f"{comparison.latest_tonnes:,.0f} tonnes")
    second.metric(
        "Year-over-year change", _format_pct(comparison.year_over_year_pct)
    )
    third.metric(
        "Same-period five-year average",
        "Not available"
        if comparison.five_year_average_tonnes is None
        else f"{comparison.five_year_average_tonnes:,.0f} tonnes",
    )
    fourth.metric(
        "Deviation from five-year average",
        _format_pct(comparison.five_year_deviation_pct),
    )

    chart_frame = selected.copy()
    chart_frame["value_numeric"] = pd.to_numeric(
        chart_frame["normalized_tonnes"], errors="coerce"
    )
    chart_frame = chart_frame.dropna(subset=["value_numeric"]).sort_values(
        "reference_date"
    )
    st.subheader(f"{snapshot_period} stocks across years")
    figure = px.line(
        chart_frame,
        x="reference_date",
        y="value_numeric",
        markers=True,
        labels={
            "reference_date": "Reference date",
            "value_numeric": "Stocks (tonnes)",
        },
    )
    st.plotly_chart(figure, width="stretch")
    st.caption(
        f"Publisher: {latest['publisher']} · Table: {latest['source_table']} · "
        f"Stock type: {latest['stock_type']} · Unit: {latest['normalized_unit']} · "
        f"Release: {latest['release_date']} · Retrieved: {latest['retrieved_at']}"
    )
    st.warning(
        "No supply-pressure score is calculated from this dataset. These stock "
        "comparisons do not include total use and are not price forecasts."
    )
    with st.expander("Latest observation provenance"):
        st.dataframe(
            latest[
                [
                    "reference_period",
                    "reference_date",
                    "source_crop",
                    "original_value",
                    "original_unit",
                    "scalar_factor",
                    "normalized_tonnes",
                    "normalized_unit",
                    "observation_status",
                    "status_marker",
                    "symbol",
                    "vector",
                    "coordinate",
                    "dguid",
                    "terminated",
                ]
            ].to_frame("value"),
            width="stretch",
        )
    st.caption(
        "Spring-wheat-specific stocks are unavailable from table 32-10-0007-01. "
        "AgSure does not treat wheat excluding durum as spring wheat."
    )


def show_statcan_supply_disposition() -> None:
    st.info(
        "Official Statistics Canada supply-and-disposition observations. "
        "Comparisons are descriptive, not price forecasts or recommendations "
        "to buy, sell, bid, or contract grain."
    )
    if not STATCAN_SUPPLY_DISPOSITION_PATH.exists():
        st.warning(
            "The processed supply-and-disposition cache is not available. Run "
            "`PYTHONPATH=src python -m agsure.statcan_supply_disposition` and "
            "reload the dashboard."
        )
        return

    frame = pd.read_csv(
        STATCAN_SUPPLY_DISPOSITION_PATH, dtype=str, keep_default_na=False
    )
    commodity_options = list(dict.fromkeys(frame["commodity"]))
    selected_slug = st.selectbox(
        "Commodity",
        options=commodity_options,
        format_func=lambda slug: COMMODITIES[slug].display_name,
    )
    available_measures = set(
        frame.loc[frame["commodity"] == selected_slug, "measure"]
    )
    measure_options = [
        measure
        for measure in SUPPLY_DISPOSITION_MEASURES
        if measure in available_measures
    ]
    measure = st.selectbox("Measure", options=measure_options)
    snapshot_options = [
        item
        for item in ("March", "July", "December")
        if item in set(frame["snapshot_period"])
    ]
    snapshot_period = st.selectbox(
        "Snapshot period", options=snapshot_options
    )

    selected = frame[
        (frame["commodity"] == selected_slug)
        & (frame["measure"] == measure)
        & (frame["snapshot_period"] == snapshot_period)
    ].copy()
    if selected.empty:
        st.warning("No source rows match the selected series.")
        return

    observations = {
        row["reference_period"]: (
            Decimal(row["normalized_tonnes"])
            if row["normalized_tonnes"]
            else None
        )
        for _, row in selected.iterrows()
    }
    try:
        comparison = compare_same_snapshot(observations)
    except ValueError as exc:
        st.warning(str(exc))
        return

    latest = selected[
        selected["reference_period"] == comparison.reference_period
    ].iloc[0]
    first, second, third, fourth = st.columns(4)
    first.metric("Latest published value", f"{comparison.latest_tonnes:,.0f} tonnes")
    second.metric("Year-over-year change", _format_pct(comparison.year_over_year_pct))
    third.metric(
        "Same-period five-year average",
        "Not available"
        if comparison.five_year_average_tonnes is None
        else f"{comparison.five_year_average_tonnes:,.0f} tonnes",
    )
    fourth.metric(
        "Deviation from five-year average",
        _format_pct(comparison.five_year_deviation_pct),
    )

    chart_frame = selected.copy()
    chart_frame["value_numeric"] = pd.to_numeric(
        chart_frame["normalized_tonnes"], errors="coerce"
    )
    chart_frame = chart_frame.dropna(subset=["value_numeric"]).sort_values(
        "reference_period"
    )
    st.subheader(f"{measure} at the {snapshot_period} snapshot across years")
    figure = px.line(
        chart_frame,
        x="reference_period",
        y="value_numeric",
        markers=True,
        labels={
            "reference_period": "Reference period",
            "value_numeric": f"{measure} (tonnes)",
        },
    )
    st.plotly_chart(figure, width="stretch")
    st.caption(
        f"Publisher: {latest['publisher']} · Table: {latest['source_table']} · "
        f"Geography: {latest['geography']} · Unit: {latest['normalized_unit']} · "
        f"Reference period: {latest['reference_period']} · "
        f"Crop year: {latest['crop_year']} · Release: {latest['release_date']} · "
        f"Retrieved: {latest['retrieved_at']}"
    )
    st.warning(
        "For these crops, Statistics Canada defines March, July, and December "
        "periods as cumulative over the August–July crop year. Exports and "
        "domestic disappearance are crop-year-to-date flows at the selected "
        "snapshot. Do not add snapshots together. Repeated production or "
        "beginning-stock values are not new observations to sum. No "
        "stocks-to-use ratio or supply-pressure score is calculated here."
    )
    with st.expander("Latest observation provenance"):
        st.dataframe(
            latest[
                [
                    "reference_period",
                    "snapshot_period",
                    "crop_year",
                    "reporting_period_start",
                    "reporting_period_end",
                    "reporting_period_basis",
                    "source_crop",
                    "source_note_ids",
                    "measure",
                    "original_value",
                    "original_unit",
                    "uom_id",
                    "scalar_factor",
                    "scalar_id",
                    "normalized_tonnes",
                    "normalized_unit",
                    "observation_status",
                    "status_marker",
                    "revision_marker",
                    "symbol",
                    "vector",
                    "coordinate",
                    "dguid",
                    "terminated",
                    "source_url",
                    "table_url",
                ]
            ].to_frame("value"),
            width="stretch",
        )
    st.caption(
        "The current cube has no spring-wheat-specific supply-and-disposition "
        "member. AgSure does not map All wheat or Wheat, excluding durum to "
        "spring wheat. Historical rows are the latest revised vintage in the "
        "current cube, not a point-in-time archive."
    )


st.set_page_config(page_title="AgSure Intelligence", page_icon="🌾", layout="wide")
st.title("AgSure Intelligence")
source = st.selectbox(
    "Data source",
    options=(
        "synthetic",
        "statcan-production",
        "statcan-stocks",
        "statcan-supply-disposition",
    ),
    format_func=lambda value: {
        "synthetic": "Synthetic demonstration data",
        "statcan-production": "Official Statistics Canada crop production",
        "statcan-stocks": "Official Statistics Canada crop stocks",
        "statcan-supply-disposition": (
            "Official Statistics Canada supply and disposition"
        ),
    }[value],
)

if source == "synthetic":
    show_synthetic()
elif source == "statcan-production":
    show_statcan_production()
elif source == "statcan-stocks":
    show_statcan_stocks()
else:
    show_statcan_supply_disposition()

with st.expander("Methodology and limitations"):
    st.markdown((ROOT / "docs" / "methodology.md").read_text(encoding="utf-8"))
