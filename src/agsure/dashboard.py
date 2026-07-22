from decimal import Decimal
import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from agsure.analysis import calculate_supply_pressure
from agsure.commodities import COMMODITIES
from agsure.crop_conditions.artifact import (
    PROVINCE_REGIONS,
    UNAVAILABLE as REGIONAL_UNAVAILABLE,
    compare_selected_period,
    options as regional_options,
    read_artifact as read_crop_conditions,
    select_series as select_regional_series,
)
from agsure.io import load_observations
from agsure.stocks import compare_same_snapshot
from agsure.statcan_supply_disposition import MEASURES as SUPPLY_DISPOSITION_MEASURES
from agsure.stocks_to_use import FORMULA, summarize_history
from agsure.unified_overview import (
    ArtifactPaths,
    DisplayObservation,
    SeriesView,
    UNAVAILABLE,
    build_overview,
)
from agsure.weather.artifact import coverage_summary, read_artifact as read_weather
from agsure.weather.common import GDD_FORMULA
from agsure.weather.config import STATIONS_BY_CLIMATE_ID


ROOT = Path(__file__).parents[2]
SYNTHETIC_PATH = ROOT / "sample_data" / "crops_synthetic.csv"
PROCESSED_DIR = Path(
    os.environ.get("AGSURE_PROCESSED_DIR", ROOT / "data" / "processed")
)
STATCAN_PRODUCTION_PATH = PROCESSED_DIR / "statcan_crop_production.csv"
STATCAN_STOCKS_PATH = PROCESSED_DIR / "statcan_crop_stocks.csv"
STATCAN_SUPPLY_DISPOSITION_PATH = PROCESSED_DIR / "statcan_supply_disposition.csv"
STATCAN_STOCKS_TO_USE_PATH = PROCESSED_DIR / "statcan_stocks_to_use.csv"
CROP_CONDITIONS_PATH = PROCESSED_DIR / "crop_conditions.csv"
WEATHER_PATH = PROCESSED_DIR / "weather.csv"
METRIC_LABELS = {
    "seeded-area": "Seeded area",
    "harvested-area": "Harvested area",
    "yield": "Yield",
    "production": "Production",
}
REGIONAL_COMMODITY_LABELS = {
    **{slug: definition.display_name for slug, definition in COMMODITIES.items()},
    "field-peas": "Field Pea",
}
REGIONAL_COMMODITIES = {
    "Alberta": ("barley", "canola", "spring-wheat", "durum-wheat", "dry-peas"),
    "Saskatchewan": ("barley", "canola", "spring-wheat", "durum-wheat", "field-peas"),
    "Manitoba": ("barley", "canola", "spring-wheat", "durum-wheat", "dry-peas"),
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


def _tonnes(value: str) -> str:
    return "Not available" if not value else f"{Decimal(value):,.0f} tonnes"


def _ratio(value: Decimal | str | None) -> str:
    if value is None or value == "":
        return "Not available"
    return f"{Decimal(value):.1f}%"


def _points(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:+.1f} pp"


def show_statcan_stocks_to_use() -> None:
    st.info(
        "Official historical stocks-to-use calculation from Statistics Canada "
        "table 32-10-0013-01. It uses completed August–July crop years only and "
        "is not a forecast, trading signal, recommendation, or validated predictor."
    )
    if not STATCAN_STOCKS_TO_USE_PATH.exists():
        st.warning(
            "The derived stocks-to-use file is not available. Run "
            "`PYTHONPATH=src python -m agsure.stocks_to_use` using the existing "
            "normalized supply-and-disposition CSV, then reload the dashboard."
        )
        return

    frame = pd.read_csv(
        STATCAN_STOCKS_TO_USE_PATH, dtype=str, keep_default_na=False
    )
    commodity_options = [
        slug for slug in COMMODITIES if slug in set(frame["commodity"])
    ]
    selected_slug = st.selectbox(
        "Commodity",
        options=commodity_options,
        format_func=lambda slug: COMMODITIES[slug].display_name,
    )
    selected = frame[frame["commodity"] == selected_slug].sort_values(
        "reference_period"
    )
    latest = selected.iloc[-1]
    selected_records = selected.to_dict("records")
    summary = None
    try:
        candidate = summarize_history(selected_records)
        if candidate.latest_crop_year == latest["crop_year"]:
            summary = candidate
    except ValueError:
        pass

    calculation_status = latest["calculation_status"]
    if calculation_status != "calculated":
        st.error(
            f"{latest['crop_year']} is unavailable: "
            f"{latest['calculation_reason'] or 'required source inputs are unavailable'}."
        )
    elif latest["reconciliation_status"] == "unreconciled":
        st.warning(
            "The latest ratio is calculable but unreconciled: the source balance "
            "difference exceeds the documented tolerance."
        )

    first, second, third = st.columns(3)
    first.metric("Latest completed crop year", latest["crop_year"])
    second.metric("Ending stocks", _tonnes(latest["ending_stocks_tonnes"]))
    third.metric("Total use", _tonnes(latest["total_use_tonnes"]))
    fourth, fifth, sixth = st.columns(3)
    fourth.metric("Stocks-to-use", _ratio(latest["stocks_to_use_pct"]))
    fifth.metric(
        "Previous-year ratio",
        _ratio(None if summary is None else summary.previous_ratio),
        delta=(
            None
            if summary is None
            else _points(summary.previous_change_percentage_points)
        ),
    )
    sixth.metric(
        "Five-year prior average",
        _ratio(None if summary is None else summary.five_year_average_ratio),
        delta=(
            None
            if summary is None
            else _points(summary.five_year_deviation_percentage_points)
        ),
    )
    st.metric(
        "Reconciliation status",
        latest["reconciliation_status"].replace("_", " ").title(),
    )

    chart_frame = selected[selected["calculation_status"] == "calculated"].copy()
    chart_frame["ratio_numeric"] = pd.to_numeric(
        chart_frame["stocks_to_use_pct"], errors="coerce"
    )
    chart_frame = chart_frame.dropna(subset=["ratio_numeric"])
    st.subheader("Historical July stocks-to-use ratio")
    if chart_frame.empty:
        st.warning("No calculated ratios are available to chart.")
    else:
        figure = px.line(
            chart_frame,
            x="crop_year",
            y="ratio_numeric",
            markers=True,
            labels={
                "crop_year": "Completed crop year",
                "ratio_numeric": "Stocks-to-use (%)",
            },
        )
        st.plotly_chart(figure, width="stretch")

    st.markdown(
        "Lower ratios mean fewer ending stocks relative to measured annual use; "
        "higher ratios mean more ending stocks relative to measured annual use. "
        "This relationship does not by itself predict price direction."
    )
    exceptions = selected[
        (selected["calculation_status"] != "calculated")
        | (selected["reconciliation_status"] == "unreconciled")
    ][
        [
            "crop_year",
            "calculation_status",
            "calculation_reason",
            "reconciliation_status",
            "reconciliation_difference_tonnes",
        ]
    ]
    if not exceptions.empty:
        st.subheader("Unavailable or unreconciled years")
        st.dataframe(exceptions, hide_index=True, width="stretch")

    with st.expander("Latest input provenance and formula details"):
        st.code(
            "total_use_tonnes = Total exports + Total domestic disappearance\n"
            "stocks_to_use_pct = Total ending stocks / total_use_tonnes * 100"
        )
        st.caption(
            f"Stored formula: {FORMULA} · Methodology version: "
            f"{latest['methodology_version']} · Reconciliation tolerance: "
            f"±{latest['reconciliation_tolerance_tonnes']} tonnes · Source vintage: "
            f"{latest['source_vintage_basis']}"
        )
        provenance_fields = [
            "publisher",
            "source_table",
            "product_id",
            "source_url",
            "table_url",
            "source_release_date",
            "source_retrieval_date",
            "reference_period",
            "snapshot_period",
            "crop_year",
            "geography",
        ] + [
            column
            for column in latest.index
            if column.startswith(
                (
                    "ending_stocks_source_",
                    "total_exports_source_",
                    "domestic_disappearance_source_",
                    "total_disposition_source_",
                )
            )
        ]
        st.dataframe(latest[provenance_fields].to_frame("value"), width="stretch")


def _display_value(item: DisplayObservation) -> str:
    if item.value is None:
        return "Not available"
    if item.unit == "percent":
        return f"{item.value:,.1f}%"
    if item.unit == "tonnes per hectare":
        return f"{item.value:,.3f} {item.unit}"
    return f"{item.value:,.0f} {item.unit}"


def _observation_caption(item: DisplayObservation) -> str:
    period = (
        f"Crop year {item.crop_year} · Reference period {item.reference_period}"
        if item.crop_year
        else f"Reference period {item.reference_period}"
    )
    return (
        f"{period} · Unit: {item.unit} · Geography: {item.geography} · "
        f"Source: {item.source_table} · Release: {item.release_date} · "
        f"Retrieved: {item.retrieved_at} · {item.observation_kind}"
    )


def _show_latest(item: DisplayObservation) -> None:
    st.metric(item.label, _display_value(item))
    st.caption(_observation_caption(item))
    st.markdown(f"[Open official source]({item.source_url})")
    with st.expander(f"{item.label} provenance · {item.reference_period}"):
        st.caption(f"Exact source identity: {item.source_label}")
        st.dataframe(
            pd.Series(dict(item.provenance), name="value").to_frame(),
            width="stretch",
        )


def _show_unavailable(series: SeriesView) -> None:
    st.warning(series.reason or UNAVAILABLE)
    st.caption(f"Requested identity: {series.identity}")


def _series_chart(series: SeriesView, title: str) -> None:
    if not series.observations:
        _show_unavailable(series)
        return
    chart_frame = pd.DataFrame(
        {
            "reference_period": [item.reference_period for item in series.observations],
            "value": [
                None if item.value is None else float(item.value)
                for item in series.observations
            ],
            "crop_year": [item.crop_year for item in series.observations],
            "unit": [item.unit for item in series.observations],
            "geography": [item.geography for item in series.observations],
            "source_table": [item.source_table for item in series.observations],
            "release_date": [item.release_date for item in series.observations],
            "retrieved_at": [item.retrieved_at for item in series.observations],
        }
    ).dropna(subset=["value"])
    if chart_frame.empty:
        _show_unavailable(series)
        return
    st.subheader(title)
    figure = px.line(
        chart_frame,
        x="reference_period",
        y="value",
        markers=True,
        hover_data=(
            "crop_year",
            "unit",
            "geography",
            "source_table",
            "release_date",
            "retrieved_at",
        ),
        labels={
            "reference_period": "Reference period",
            "value": series.observations[-1].unit,
        },
    )
    st.plotly_chart(figure, width="stretch")
    if series.latest is not None:
        _show_latest(series.latest)
    if not series.available:
        _show_unavailable(series)


def _regional_rows() -> list[dict[str, str]] | None:
    try:
        return read_crop_conditions(CROP_CONDITIONS_PATH)
    except (FileNotFoundError, ValueError) as exc:
        st.warning(str(exc))
        return None


def _regional_metric(row: dict[str, str]) -> str:
    return "Not available" if not row["value"] else f"{Decimal(row['value']):,.1f}%"


def _show_regional_provenance(row: dict[str, str]) -> None:
    st.caption(
        f"Reporting period: {row['reporting_period_start'] or 'not published'} to "
        f"{row['reporting_period_end']} · Release: {row['release_date']} · "
        f"Unit: {row['unit']} · Status: {row['observation_status']} · "
        f"Extraction: {row['extraction_method']} · Retrieved: {row['retrieved_at']}"
    )
    st.markdown(f"[Open official report]({row['source_document_url']})")


def show_crop_conditions() -> None:
    st.info(
        "Official weekly regional crop-report observations. Province reporting "
        "systems, crop terms, condition definitions, and periods differ and are "
        "not interchangeable. These observations are not forecasts or trading signals."
    )
    rows = _regional_rows()
    if rows is None:
        return
    province = st.selectbox(
        "Province", options=tuple(PROVINCE_REGIONS), key="regional_province"
    )
    region_pairs = PROVINCE_REGIONS[province]
    source_region_id = st.selectbox(
        "Official source region",
        options=[item[1] for item in region_pairs],
        format_func=dict((identifier, label) for label, identifier in region_pairs).get,
        key=f"regional_region_{province}",
    )
    commodity = st.selectbox(
        "Commodity",
        options=REGIONAL_COMMODITIES[province],
        format_func=REGIONAL_COMMODITY_LABELS.get,
        key=f"regional_commodity_{province}",
    )
    if commodity == "field-peas":
        st.caption(
            "Field Pea is the Saskatchewan report's exact crop identity; it is "
            "not treated as equivalent to Statistics Canada's Dry Peas series."
        )
    observation_types = regional_options(
        rows, "observation_type", province=province,
        source_region_id=source_region_id, commodity=commodity,
    )
    if not observation_types:
        st.warning(
            f"{REGIONAL_UNAVAILABLE}: {province} / "
            f"{dict((identifier, label) for label, identifier in region_pairs)[source_region_id]} / "
            f"{REGIONAL_COMMODITY_LABELS[commodity]}. The source may publish only "
            "narrative or an incompatible crop identity."
        )
        return
    observation_type = st.selectbox(
        "Observation type", options=observation_types,
        key=f"regional_observation_type_{province}_{source_region_id}_{commodity}",
    )
    measures = regional_options(
        rows, "source_measure", province=province, source_region_id=source_region_id,
        commodity=commodity, observation_type=observation_type,
    )
    source_measure = st.selectbox(
        "Exact source measure", options=measures,
        key=(f"regional_measure_{province}_{source_region_id}_{commodity}_"
             f"{observation_type}"),
    )
    categories = regional_options(
        rows, "category", province=province, source_region_id=source_region_id,
        commodity=commodity, observation_type=observation_type,
        source_measure=source_measure,
    )
    category = st.selectbox(
        "Category", options=categories,
        key=(f"regional_category_{province}_{source_region_id}_{commodity}_"
             f"{observation_type}_{source_measure}"),
    )
    series = select_regional_series(
        rows, province=province, source_region_id=source_region_id,
        commodity=commodity, observation_type=observation_type,
        source_measure=source_measure, category=category,
    )
    periods = [row["reporting_period_end"] for row in series.rows]
    selected_period = st.selectbox(
        "Reporting period", options=periods, index=len(periods) - 1,
        key=(f"regional_reporting_period_{province}_{source_region_id}_{commodity}_"
             f"{observation_type}_{source_measure}_{category}"),
    )
    comparison = compare_selected_period(series.rows, selected_period)
    selected_row = comparison.selected
    first, second, third = st.columns(3)
    first.metric("Selected official observation", _regional_metric(selected_row))
    second.metric(
        "Previous comparable report",
        "Not available" if comparison.previous is None
        else _regional_metric(comparison.previous),
    )
    third.metric(
        "Change",
        "Not available" if comparison.change_percentage_points is None
        else f"{comparison.change_percentage_points:+.1f} pp",
    )
    _show_regional_provenance(selected_row)
    chart_rows = [row for row in series.rows if row["value"]]
    if chart_rows:
        chart = pd.DataFrame(
            {
                "reporting_period_end": [row["reporting_period_end"] for row in chart_rows],
                "value": [float(row["value"]) for row in chart_rows],
            }
        )
        st.plotly_chart(
            px.line(
                chart,
                x="reporting_period_end",
                y="value",
                markers=True,
                labels={"reporting_period_end": "Reporting period end", "value": "Percent"},
            ),
            width="stretch",
        )
    st.info("No source-published baseline is available for this exact selected identity.")
    with st.expander("Selected observation provenance"):
        st.dataframe(pd.Series(selected_row, name="value").to_frame(), width="stretch")
    st.warning(
        "Weekly crop conditions can change rapidly and may not translate directly "
        "into final production, yield, price, bids, or stocks-to-use."
    )


def show_compact_regional_conditions(commodity: str) -> None:
    st.subheader("Regional crop conditions")
    st.caption(
        "Separate weekly provincial crop reports; not Canada-level annual "
        "production and not an input to the synthetic 72.1/100 score."
    )
    rows = _regional_rows()
    if rows is None:
        return
    province = st.selectbox(
        "Regional source province",
        options=tuple(PROVINCE_REGIONS),
        index=None,
        placeholder="Select a province",
        key="unified_regional_province",
    )
    if province is None:
        st.info("Select a province and its official source region to show observations.")
        return
    region_pairs = PROVINCE_REGIONS[province]
    source_region_id = st.selectbox(
        "Regional official source region",
        options=[item[1] for item in region_pairs],
        index=None,
        placeholder="Select an official region",
        format_func=dict((identifier, label) for label, identifier in region_pairs).get,
        key=f"unified_regional_region_{province}",
    )
    if source_region_id is None:
        st.info("Select an official source region to show observations.")
        return
    candidates = [
        row for row in rows
        if row["province"] == province
        and row["source_region_id"] == source_region_id
        and row["commodity"] == commodity
        and row["value"]
    ]
    if not candidates:
        st.warning(
            f"{REGIONAL_UNAVAILABLE}: {province} / {source_region_id} / "
            f"{COMMODITIES[commodity].display_name}."
        )
        return
    latest_period = max(row["reporting_period_end"] for row in candidates)
    latest = [row for row in candidates if row["reporting_period_end"] == latest_period]
    for row in latest[:5]:
        label = row["source_measure"] + (f" · {row['category']}" if row["category"] else "")
        st.metric(label, _regional_metric(row))
    _show_regional_provenance(latest[0])
    st.warning("Regional systems and condition definitions differ by province.")


WEATHER_LABELS = {
    "001": "Maximum temperature",
    "002": "Minimum temperature",
    "003": "Mean temperature",
    "012": "Total precipitation",
    "agsure:daily-gdd-v1": "Daily GDD (base 5°C)",
}


def _weather_rows() -> list[dict[str, str]] | None:
    try:
        return read_weather(WEATHER_PATH)
    except (FileNotFoundError, ValueError) as exc:
        st.warning(str(exc))
        return None


def _weather_value(row: dict[str, str]) -> str:
    if not row["normalized_value"]:
        return "Not available"
    value = Decimal(row["normalized_value"])
    if row["normalized_unit"] == "degrees Celsius":
        return f"{value:,.1f}°C"
    if row["normalized_unit"] == "millimetres":
        return f"{value:,.1f} mm"
    return f"{value:,.2f} degree-days"


def _show_weather_day(day_rows: list[dict[str, str]]) -> None:
    by_element = {row["source_element_identifier"]: row for row in day_rows}
    for offset in range(0, len(WEATHER_LABELS), 5):
        columns = st.columns(5)
        for column, element in zip(columns, tuple(WEATHER_LABELS)[offset : offset + 5]):
            with column:
                row = by_element[element]
                st.metric(WEATHER_LABELS[element], _weather_value(row))
                origin = (
                    "Calculated by AgSure"
                    if row["observation_origin"] == "calculated"
                    else "Source-published by ECCC"
                )
                flag = row["source_quality_flag"] or "none"
                st.caption(
                    f"{origin} · Status: {row['observation_status']} · Flag: {flag}"
                )


def _show_weather_provenance(row: dict[str, str]) -> None:
    st.caption(
        f"Official station: {row['official_station_name']} · Climate ID: "
        f"{row['station_identifier']} · {row['latitude']}, {row['longitude']} · "
        f"Elevation: {row['elevation']} {row['elevation_unit']} · "
        f"Retrieved: {row['retrieved_at']} · Release date: unavailable from source"
    )
    st.markdown(f"[Open official ECCC API query]({row['source_url']})")


def _weather_station_selector(
    rows: list[dict[str, str]], *, key: str, label: str = "Official weather station"
) -> str | None:
    available = tuple(
        station.climate_id
        for station in STATIONS_BY_CLIMATE_ID.values()
        if any(row["station_identifier"] == station.climate_id for row in rows)
    )
    return st.selectbox(
        label, options=available, index=None, placeholder="Select a station",
        format_func=lambda identifier: (
            f"{STATIONS_BY_CLIMATE_ID[identifier].name} · Climate ID {identifier}"
        ),
        key=key,
    )


def show_weather() -> None:
    st.info(
        "Official ECCC historical daily observations for individual stations. "
        "No station is a Southern Alberta regional estimate, and no values are "
        "interpolated, averaged, forecast, or used in the supply-pressure score."
    )
    rows = _weather_rows()
    if rows is None:
        return
    st.caption(coverage_summary(rows))
    station_id = _weather_station_selector(rows, key="weather_station")
    if station_id is None:
        st.info("Select an official station before choosing a date or period.")
        return
    station_rows = [row for row in rows if row["station_identifier"] == station_id]
    dates = tuple(dict.fromkeys(row["reference_date"] for row in station_rows))
    start = st.selectbox(
        "Period start", options=dates, index=None, placeholder="Select a start date",
        key=f"weather_start_{station_id}",
    )
    if start is None:
        st.info("Select a period start date to show station observations.")
        return
    end_options = tuple(value for value in dates if value >= start)
    end = st.selectbox(
        "Period end", options=end_options, index=None, placeholder="Select an end date",
        key=f"weather_end_{station_id}_{start}",
    )
    if end is None:
        st.info("Select a period end date; use the same date for a one-day view.")
        return
    selected = [row for row in station_rows if start <= row["reference_date"] <= end]
    end_rows = [row for row in selected if row["reference_date"] == end]
    st.subheader(f"{STATIONS_BY_CLIMATE_ID[station_id].name} · {start} to {end}")
    _show_weather_day(end_rows)
    _show_weather_provenance(end_rows[0])

    chart_source = [
        row for row in selected
        if row["source_element_identifier"] in WEATHER_LABELS
    ]
    valid = [row for row in chart_source if row["normalized_value"]]
    valid_dates = {row["reference_date"] for row in valid}
    if len(valid_dates) < 2:
        st.caption("A line chart is not shown because fewer than two dates have values.")
    else:
        chart = pd.DataFrame({
            "reference_date": [row["reference_date"] for row in chart_source],
            "value": [
                None if not row["normalized_value"] else float(row["normalized_value"])
                for row in chart_source
            ],
            "element": [WEATHER_LABELS[row["source_element_identifier"]] for row in chart_source],
            "status": [row["observation_status"] for row in chart_source],
        })
        figure = px.line(
            chart, x="reference_date", y="value", color="element", markers=True,
            hover_data=("status",),
            labels={"reference_date": "Reference date", "value": "Published or calculated value"},
        )
        figure.update_traces(connectgaps=False)
        st.plotly_chart(figure, width="stretch")

    completeness = []
    for element, label in WEATHER_LABELS.items():
        element_rows = [row for row in selected if row["source_element_identifier"] == element]
        available = sum(bool(row["normalized_value"]) for row in element_rows)
        completeness.append({
            "element": label, "available days": available,
            "unavailable days": len(element_rows) - available,
            "selected days": len(element_rows),
        })
    st.subheader("Selected-period completeness")
    st.dataframe(pd.DataFrame(completeness), hide_index=True, width="stretch")
    exceptions = [row for row in selected if not row["normalized_value"]]
    if exceptions:
        st.subheader("Explicit unavailable observations")
        st.dataframe(pd.DataFrame(exceptions)[[
            "reference_date", "source_element_label", "observation_status",
            "raw_source_value", "source_quality_flag",
        ]], hide_index=True, width="stretch")
    with st.expander("Selected end-date provenance and GDD methodology"):
        st.code(f"daily GDD = {GDD_FORMULA}\nbase temperature = 5°C (v0.8 convention)")
        st.caption(
            "GDD requires unflagged source-published maximum and minimum temperatures "
            "from this exact station and date. It is not an official ECCC observation "
            "and 5°C is not asserted to suit every crop."
        )
        st.dataframe(pd.DataFrame(end_rows), hide_index=True, width="stretch")


def show_compact_weather() -> None:
    st.subheader("Official station weather")
    st.caption(
        "Separate station-specific ECCC observations; not a Southern Alberta average "
        "and not an input to the synthetic 72.1/100 score."
    )
    rows = _weather_rows()
    if rows is None:
        return
    st.caption(coverage_summary(rows))
    station_id = _weather_station_selector(
        rows, key="unified_weather_station", label="Overview weather station"
    )
    if station_id is None:
        st.info("Select an official weather station before showing values.")
        return
    dates = tuple(dict.fromkeys(
        row["reference_date"] for row in rows if row["station_identifier"] == station_id
    ))
    selected_date = st.selectbox(
        "Overview weather reference date", options=dates, index=None,
        placeholder="Select a reference date", key=f"unified_weather_date_{station_id}",
    )
    if selected_date is None:
        st.info("Select a weather reference date to show station values.")
        return
    day_rows = [
        row for row in rows
        if row["station_identifier"] == station_id and row["reference_date"] == selected_date
    ]
    _show_weather_day(day_rows)
    _show_weather_provenance(day_rows[0])
    st.warning("These values describe only the selected station and date.")


def show_unified_overview() -> None:
    st.info(
        "Unified official commodity overview. Official published observations, "
        "derived official calculations, and synthetic demonstrations remain "
        "strictly separate. No real-data supply-pressure score is calculated."
    )
    paths = ArtifactPaths(
        production=STATCAN_PRODUCTION_PATH,
        stocks=STATCAN_STOCKS_PATH,
        supply_disposition=STATCAN_SUPPLY_DISPOSITION_PATH,
        stocks_to_use=STATCAN_STOCKS_TO_USE_PATH,
    )
    commodity = st.selectbox(
        "Commodity",
        options=list(COMMODITIES),
        format_func=lambda slug: COMMODITIES[slug].display_name,
        key="unified_commodity",
    )
    try:
        initial = build_overview(paths, commodity)
    except ValueError as exc:
        st.error(f"Unified overview validation failed: {exc}")
        return
    geography = st.selectbox(
        "Production and stocks geography",
        options=initial.geography_options,
        help=(
            "This selection applies only to production and stocks. Supply and "
            "disposition and stocks-to-use remain explicitly Canada-level."
        ),
        key="unified_geography",
    )
    try:
        choices = build_overview(paths, commodity, geography)
    except ValueError as exc:
        st.error(f"Unified overview validation failed: {exc}")
        return

    stock_type = None
    stock_snapshot = None
    if choices.stock_type_options:
        stock_type = st.selectbox(
            "Stocks type",
            options=choices.stock_type_options,
            index=choices.stock_type_options.index(choices.stock_type),
            key="unified_stock_type",
        )
        stock_choices = build_overview(
            paths, commodity, geography, stock_type=stock_type
        )
        if stock_choices.stock_snapshot_options:
            stock_snapshot = st.selectbox(
                "Stocks comparison period",
                options=stock_choices.stock_snapshot_options,
                index=stock_choices.stock_snapshot_options.index(
                    stock_choices.stock_snapshot
                ),
                key="unified_stock_snapshot",
            )

    supply_measure = None
    supply_snapshot = None
    if choices.supply_measure_options:
        supply_measure = st.selectbox(
            "Supply-and-disposition measure",
            options=choices.supply_measure_options,
            index=choices.supply_measure_options.index(choices.supply_measure),
            key="unified_supply_measure",
        )
        supply_choices = build_overview(
            paths, commodity, geography, supply_measure=supply_measure
        )
        if supply_choices.supply_snapshot_options:
            supply_snapshot = st.selectbox(
                "Supply-and-disposition comparison period",
                options=supply_choices.supply_snapshot_options,
                index=supply_choices.supply_snapshot_options.index(
                    supply_choices.supply_snapshot
                ),
                key="unified_supply_snapshot",
            )

    try:
        overview = build_overview(
            paths,
            commodity,
            geography,
            stock_type=stock_type,
            stock_snapshot=stock_snapshot,
            supply_measure=supply_measure,
            supply_snapshot=supply_snapshot,
        )
    except ValueError as exc:
        st.error(f"Unified overview validation failed: {exc}")
        return

    st.caption(
        "Geography boundary: production and stocks below use "
        f"{geography}; supply and disposition and stocks-to-use use Canada."
    )
    tabs = st.tabs(
        (
            "Latest snapshot",
            "Production",
            "Stocks",
            "Supply and disposition",
            "Stocks-to-use",
            "Data availability and provenance",
        )
    )
    with tabs[0]:
        st.subheader(f"Latest official indicators · {COMMODITIES[commodity].display_name}")
        for offset in range(0, len(overview.snapshot), 4):
            columns = st.columns(4)
            for column, item in zip(columns, overview.snapshot[offset : offset + 4]):
                with column:
                    _show_latest(item)
        unavailable_snapshot = [
            series for series in (*overview.production.values(), overview.stocks, overview.stocks_to_use)
            if not series.available
        ]
        for series in unavailable_snapshot:
            _show_unavailable(series)
        st.divider()
        show_compact_regional_conditions(commodity)
        st.divider()
        show_compact_weather()

    with tabs[1]:
        metric = st.selectbox(
            "Production measure",
            options=list(METRIC_LABELS),
            format_func=lambda value: METRIC_LABELS[value],
            index=3,
            key="unified_production_metric",
        )
        _series_chart(
            overview.production[metric],
            f"{METRIC_LABELS[metric]} history · {geography}",
        )

    with tabs[2]:
        st.caption(
            f"Exact series: {overview.stocks.identity}. Only "
            f"{overview.stock_snapshot or 'the selected'} snapshots are compared."
        )
        _series_chart(overview.stocks, "Same-snapshot stocks history")

    with tabs[3]:
        st.warning(
            "Canada-level only. This section does not describe the selected "
            f"{geography} geography. March, July, and December are cumulative "
            "snapshots and must not be added."
        )
        st.caption(
            f"Exact series: {overview.supply_disposition.identity}. Only one "
            "measure and one snapshot period are compared across years."
        )
        _series_chart(
            overview.supply_disposition,
            "Same-measure, same-snapshot supply-and-disposition history",
        )

    with tabs[4]:
        st.warning(
            "Canada-level July observations for completed August–July crop years "
            "only. This derived official calculation is not a forecast, trading "
            "signal, recommendation, or validated predictor."
        )
        _series_chart(overview.stocks_to_use, "Historical July stocks-to-use")

    with tabs[5]:
        availability = []
        for name, series in (
            ("Production", overview.production["production"]),
            ("Stocks", overview.stocks),
            ("Supply and disposition", overview.supply_disposition),
            ("Stocks-to-use", overview.stocks_to_use),
        ):
            availability.append(
                {
                    "section": name,
                    "status": "Available" if series.available else "Unavailable",
                    "selected identity": series.identity,
                    "reason": series.reason,
                }
            )
        st.dataframe(pd.DataFrame(availability), hide_index=True, width="stretch")
        for name, error in overview.artifact_errors.items():
            st.warning(f"{name}: {error}")
        st.markdown(
            "Historical official rows represent the latest revised cube vintage "
            "at retrieval, not a point-in-time archive. Values are never "
            "interpolated, repaired, or replaced with aggregate wheat members."
        )


st.set_page_config(page_title="AgSure Intelligence", page_icon="🌾", layout="wide")
st.title("AgSure Intelligence")
source = st.selectbox(
    "Data source",
    options=(
        "unified",
        "synthetic",
        "statcan-production",
        "statcan-stocks",
        "statcan-supply-disposition",
        "statcan-stocks-to-use",
        "crop-conditions",
        "weather",
    ),
    format_func=lambda value: {
        "unified": "Unified commodity overview",
        "synthetic": "Synthetic demonstration data",
        "statcan-production": "Official Statistics Canada crop production",
        "statcan-stocks": "Official Statistics Canada crop stocks",
        "statcan-supply-disposition": (
            "Official Statistics Canada supply and disposition"
        ),
        "statcan-stocks-to-use": "Official stocks-to-use",
        "crop-conditions": "Official regional crop conditions",
        "weather": "Official Southern Alberta station weather",
    }[value],
)

if source == "unified":
    show_unified_overview()
elif source == "synthetic":
    show_synthetic()
elif source == "statcan-production":
    show_statcan_production()
elif source == "statcan-stocks":
    show_statcan_stocks()
elif source == "statcan-supply-disposition":
    show_statcan_supply_disposition()
elif source == "statcan-stocks-to-use":
    show_statcan_stocks_to_use()
elif source == "crop-conditions":
    show_crop_conditions()
else:
    show_weather()

with st.expander("Methodology and limitations"):
    st.markdown((ROOT / "docs" / "methodology.md").read_text(encoding="utf-8"))
