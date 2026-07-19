from decimal import Decimal
import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from agsure.analysis import calculate_supply_pressure
from agsure.commodities import COMMODITIES
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


ROOT = Path(__file__).parents[2]
SYNTHETIC_PATH = ROOT / "sample_data" / "crops_synthetic.csv"
PROCESSED_DIR = Path(
    os.environ.get("AGSURE_PROCESSED_DIR", ROOT / "data" / "processed")
)
STATCAN_PRODUCTION_PATH = PROCESSED_DIR / "statcan_crop_production.csv"
STATCAN_STOCKS_PATH = PROCESSED_DIR / "statcan_crop_stocks.csv"
STATCAN_SUPPLY_DISPOSITION_PATH = PROCESSED_DIR / "statcan_supply_disposition.csv"
STATCAN_STOCKS_TO_USE_PATH = PROCESSED_DIR / "statcan_stocks_to_use.csv"
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
else:
    show_statcan_stocks_to_use()

with st.expander("Methodology and limitations"):
    st.markdown((ROOT / "docs" / "methodology.md").read_text(encoding="utf-8"))
