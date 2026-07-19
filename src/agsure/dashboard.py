from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from agsure.analysis import calculate_supply_pressure
from agsure.commodities import COMMODITIES
from agsure.io import load_observations


DATA_PATH = Path(__file__).parents[2] / "sample_data" / "crops_synthetic.csv"

st.set_page_config(page_title="AgSure Intelligence", page_icon="🌾", layout="wide")
st.title("AgSure Intelligence")
st.error("Synthetic demonstration data — not a crop forecast or trading recommendation.")

frame = pd.read_csv(DATA_PATH)
selected_slug = st.selectbox(
    "Commodity",
    options=list(COMMODITIES),
    format_func=lambda slug: COMMODITIES[slug].display_name,
)
commodity = COMMODITIES[selected_slug]
observations = [
    item for item in load_observations(DATA_PATH) if item.commodity == selected_slug
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

st.subheader("Production history")
figure = px.line(
    selected_frame,
    x="crop_year",
    y="production_kt",
    markers=True,
    labels={"crop_year": "Crop year", "production_kt": "Production (kt)"},
)
st.plotly_chart(figure, use_container_width=True)

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
    st.dataframe(components, hide_index=True, use_container_width=True)

with st.expander("Methodology and limitations"):
    methodology = Path(__file__).parents[2] / "docs" / "methodology.md"
    st.markdown(methodology.read_text(encoding="utf-8"))
