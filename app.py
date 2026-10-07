from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.supply_chain_risk.analytics import (
    HIGH_RISK_THRESHOLD,
    RISK_WEIGHTS,
    apply_weight_scenario,
    build_analysis,
)


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"

st.set_page_config(page_title="Supplier Risk & Resilience", page_icon="✈️", layout="wide")


@st.cache_data
def get_analysis():
    return build_analysis(DATA_DIR)


tables, supplier_scores, part_risk, kpis = get_analysis()

st.title("Aerospace Supplier Risk & Resilience")
st.caption(
    "Synthetic portfolio project · 12 months of procurement history · "
    "Risk scores are decision-support indicators, not predictions"
)

with st.sidebar:
    st.header("Filters")
    selected_regions = st.multiselect(
        "Supplier region", sorted(supplier_scores["region"].unique()),
        default=sorted(supplier_scores["region"].unique()),
    )
    selected_tiers = st.multiselect(
        "Risk tier", ["High", "Medium", "Low"], default=["High", "Medium", "Low"]
    )
    selected_criticality = st.multiselect(
        "Part criticality", ["Critical", "High", "Standard"],
        default=["Critical", "High", "Standard"],
    )
    st.divider()
    st.markdown("**Risk model weights**")
    for component, weight in RISK_WEIGHTS.items():
        st.caption(f"{component.replace('_', ' ').title()}: {weight:.0%}")

filtered_suppliers = supplier_scores[
    supplier_scores["region"].isin(selected_regions)
    & supplier_scores["risk_tier"].isin(selected_tiers)
].copy()
filtered_parts = part_risk[part_risk["criticality"].isin(selected_criticality)].copy()

metric_cols = st.columns(5)
metric_cols[0].metric(
    "High-risk suppliers",
    kpis["high_risk_suppliers"],
    help=f"Risk score ≥ {HIGH_RISK_THRESHOLD:.0f}; threshold reflects the synthetic risk appetite",
)
metric_cols[1].metric("Critical spend exposed", f"${kpis['critical_spend_exposed']/1_000_000:.1f}M")
metric_cols[2].metric("Single-source parts", kpis["single_source_parts"])
metric_cols[3].metric("Potential stockouts", kpis["potential_stockouts"])
metric_cols[4].metric("On-time delivery", f"{kpis['on_time_delivery_rate']:.1%}")

st.divider()
left, right = st.columns([1.15, 0.85])
with left:
    st.subheader("Supplier risk ranking")
    ranking = filtered_suppliers.nlargest(12, "risk_score").sort_values("risk_score")
    fig = px.bar(
        ranking,
        x="risk_score",
        y="supplier_name",
        orientation="h",
        color_discrete_sequence=["#315F85"],
        labels={"risk_score": "Risk score (0–100)", "supplier_name": "Supplier"},
        hover_data=["country", "risk_tier", "on_time_delivery_rate", "defect_rate"],
    )
    fig.update_layout(height=450, showlegend=False, margin=dict(l=10, r=15, t=10, b=10))
    fig.update_xaxes(range=[0, 100])
    st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("Risk versus open spend")
    fig = px.scatter(
        filtered_suppliers,
        x="risk_score",
        y="spend",
        size="supplied_parts",
        color="risk_tier",
        hover_name="supplier_name",
        hover_data=["country", "on_time_delivery_rate", "defect_rate"],
        color_discrete_map={"High": "#B85C38", "Medium": "#D5A23F", "Low": "#315F85"},
        labels={"risk_score": "Risk score", "spend": "12-month PO value", "risk_tier": "Risk tier"},
    )
    fig.update_layout(height=450, margin=dict(l=10, r=15, t=10, b=10))
    fig.update_yaxes(tickprefix="$", tickformat="~s")
    st.plotly_chart(fig, use_container_width=True)

left, right = st.columns(2)
with left:
    st.subheader("Average supplier risk by region")
    regional = filtered_suppliers.groupby("region", as_index=False).agg(
        average_risk=("risk_score", "mean"), suppliers=("supplier_id", "nunique")
    ).sort_values("average_risk", ascending=False)
    fig = px.bar(
        regional,
        x="region",
        y="average_risk",
        color_discrete_sequence=["#315F85"],
        labels={"region": "Region", "average_risk": "Average risk score"},
        hover_data=["suppliers"],
    )
    fig.update_layout(height=350, showlegend=False, margin=dict(l=10, r=15, t=10, b=10))
    fig.update_yaxes(range=[0, 100])
    st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("Risk components for selected supplier")
    supplier_choices = filtered_suppliers["supplier_name"].tolist()
    if supplier_choices:
        selected_supplier = st.selectbox("Supplier", supplier_choices, label_visibility="collapsed")
        row = filtered_suppliers.loc[filtered_suppliers["supplier_name"] == selected_supplier].iloc[0]
        components = list(RISK_WEIGHTS)
        labels = [name.replace("_", " ").title() for name in components]
        values = [float(row[name]) for name in components]
        fig = go.Figure(go.Bar(x=values, y=labels, orientation="h", marker_color="#315F85"))
        fig.update_layout(height=305, margin=dict(l=10, r=15, t=10, b=10), xaxis_title="Component score")
        fig.update_xaxes(range=[0, 100])
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No suppliers match the selected filters.")

st.subheader("Parts requiring action")
action_parts = filtered_parts[filtered_parts["recommended_action"] != "Monitor"].copy()
display_columns = [
    "part_id", "part_name", "category", "criticality", "supplier_count",
    "days_of_supply", "average_lead_time_days", "part_risk_score", "recommended_action",
]
st.dataframe(
    action_parts[display_columns].head(30),
    use_container_width=True,
    hide_index=True,
    column_config={
        "days_of_supply": st.column_config.NumberColumn(format="%.1f"),
        "average_lead_time_days": st.column_config.NumberColumn(format="%.1f"),
        "part_risk_score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
    },
)

st.divider()
st.header("Weight sensitivity lab")
st.caption(
    "Adjust management priorities to test whether the supplier ranking is robust. "
    "Inputs are automatically normalized to 100%, so the relative emphasis matters."
)

DELIVERY_DISRUPTION_WEIGHTS = {
    "delivery_risk": 45,
    "quality_risk": 10,
    "lead_time_variability_risk": 20,
    "geographic_risk": 10,
    "financial_risk": 5,
    "dependency_risk": 10,
}

weight_columns = st.columns(3)
scenario_weights = {}
component_labels = {
    "delivery_risk": "Delivery",
    "quality_risk": "Quality",
    "lead_time_variability_risk": "Lead-time variability",
    "geographic_risk": "Geographic exposure",
    "financial_risk": "Financial health",
    "dependency_risk": "Dependency",
}


def set_scenario_weights(weights):
    for component, value in weights.items():
        st.session_state[f"weight_{component}"] = int(value)


control_columns = st.columns([1, 1, 2])
control_columns[0].button(
    "Load disruption scenario",
    on_click=set_scenario_weights,
    args=(DELIVERY_DISRUPTION_WEIGHTS,),
    use_container_width=True,
)
control_columns[1].button(
    "Reset to baseline",
    on_click=set_scenario_weights,
    args=({name: int(weight * 100) for name, weight in RISK_WEIGHTS.items()},),
    use_container_width=True,
)

for index, (component, default_weight) in enumerate(RISK_WEIGHTS.items()):
    with weight_columns[index % 3]:
        scenario_weights[component] = st.slider(
            component_labels[component],
            min_value=0,
            max_value=60,
            value=DELIVERY_DISRUPTION_WEIGHTS[component],
            step=5,
            key=f"weight_{component}",
            help="Relative importance; all six values are normalized after selection.",
        )

normalized_total = sum(scenario_weights.values())
if normalized_total == 0:
    st.warning("At least one weight must be greater than zero. Baseline weights are shown instead.")
    scenario_weights = {name: int(weight * 100) for name, weight in RISK_WEIGHTS.items()}
    normalized_total = sum(scenario_weights.values())
scenario = apply_weight_scenario(supplier_scores, scenario_weights)
baseline_percentages = {
    name: int(weight * 100) for name, weight in RISK_WEIGHTS.items()
}
is_baseline = scenario_weights == baseline_percentages
is_delivery_disruption = scenario_weights == DELIVERY_DISRUPTION_WEIGHTS
normalized_copy = ", ".join(
    f"{component_labels[name]} {value / normalized_total:.0%}"
    for name, value in scenario_weights.items()
) if normalized_total else "No valid scenario"
if is_baseline:
    scenario_name = "Current Policy (baseline)"
elif is_delivery_disruption:
    scenario_name = "Delivery Disruption Scenario"
else:
    scenario_name = "Custom Scenario"
st.caption(f"**Active scenario: {scenario_name}** · Normalized weights: {normalized_copy}")
if is_baseline:
    st.info(
        "The scenario currently matches Current Policy, so scores and rankings are identical. "
        "Adjust a weight or load the disruption scenario to compare outcomes."
    )

baseline_top10 = set(supplier_scores.nlargest(10, "risk_score")["supplier_id"])
scenario_top10 = set(scenario.nsmallest(10, "scenario_rank")["supplier_id"])
top10_overlap = len(baseline_top10 & scenario_top10)
rank_correlation = scenario[["baseline_rank", "scenario_rank"]].corr(method="spearman").iloc[0, 1]
tier_changes = int(scenario["tier_changed"].sum())

sensitivity_metrics = st.columns(3)
sensitivity_metrics[0].metric("Top-10 suppliers retained", f"{top10_overlap}/10")
sensitivity_metrics[1].metric("Rank stability", f"{rank_correlation:.2f}", help="Spearman rank correlation; 1.00 means identical ordering")
sensitivity_metrics[2].metric("Suppliers changing risk tier", tier_changes)

comparison_ids = list(
    dict.fromkeys(
        scenario.nsmallest(8, "scenario_rank")["supplier_id"].tolist()
        + supplier_scores.nlargest(8, "risk_score")["supplier_id"].tolist()
    )
)
comparison = scenario[scenario["supplier_id"].isin(comparison_ids)][
    ["supplier_name", "risk_score", "scenario_score"]
].melt(
    id_vars="supplier_name",
    value_vars=["risk_score", "scenario_score"],
    var_name="score_type",
    value_name="score",
)
comparison["score_type"] = comparison["score_type"].map(
    {"risk_score": "Current Policy", "scenario_score": scenario_name}
)
fig = px.bar(
    comparison,
    x="score",
    y="supplier_name",
    color="score_type",
    barmode="group",
    orientation="h",
    color_discrete_map={"Current Policy": "#A9B4BF", scenario_name: "#315F85"},
    labels={"score": "Risk score (0–100)", "supplier_name": "Supplier", "score_type": "Scoring model"},
)
fig.update_layout(height=520, margin=dict(l=10, r=15, t=10, b=10), legend_orientation="h")
fig.update_xaxes(range=[0, 100])
st.subheader("Current Policy and scenario scores")
st.plotly_chart(fig, use_container_width=True)

st.subheader("Largest ranking changes")
movers = scenario.loc[scenario["rank_change"].ne(0)].assign(
    abs_rank_change=lambda frame: frame["rank_change"].abs()
).nlargest(
    12, "abs_rank_change"
)
if movers.empty:
    st.info(
        "No suppliers changed rank because the scenario matches Current Policy. "
        "Adjust a weight or load the disruption scenario to reveal ranking sensitivity."
    )
else:
    st.dataframe(
        movers[
            [
                "supplier_name", "baseline_rank", "scenario_rank", "rank_change",
                "risk_score", "scenario_score", "risk_tier", "scenario_risk_tier",
            ]
        ],
        use_container_width=True,
        hide_index=True,
        column_config={
            "baseline_rank": st.column_config.NumberColumn("Current Policy rank"),
            "scenario_rank": st.column_config.NumberColumn("Scenario rank"),
            "rank_change": st.column_config.NumberColumn(
                "Rank movement", help="Positive values move closer to rank 1"
            ),
            "risk_score": st.column_config.NumberColumn("Current Policy score", format="%.1f"),
            "scenario_score": st.column_config.NumberColumn("Scenario score", format="%.1f"),
        },
    )

with st.expander("Methodology and limitations"):
    st.markdown(
        """
        - Supplier scores combine delivery, quality, lead-time variability, geographic, financial, and dependency risk.
        - A potential stockout occurs when current days of supply are below average replenishment lead time.
        - All data is synthetic and generated deterministically for demonstration.
        - Production use would require ERP and quality-system integration, metric ownership, score calibration, and refresh monitoring.
        - The sensitivity lab tests decision robustness; it does not prove that any chosen set of weights is objectively correct.
        """
    )

PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
supplier_scores.to_csv(PROCESSED_DIR / "supplier_scores.csv", index=False)
part_risk.to_csv(PROCESSED_DIR / "part_risk.csv", index=False)

