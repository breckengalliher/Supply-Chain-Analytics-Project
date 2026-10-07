from __future__ import annotations

from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd


RISK_WEIGHTS: Mapping[str, float] = {
    "delivery_risk": 0.30,
    "quality_risk": 0.20,
    "lead_time_variability_risk": 0.15,
    "geographic_risk": 0.15,
    "financial_risk": 0.10,
    "dependency_risk": 0.10,
}

MEDIUM_RISK_THRESHOLD = 25.0
HIGH_RISK_THRESHOLD = 35.0

REQUIRED_COLUMNS = {
    "suppliers": {
        "supplier_id", "supplier_name", "country", "region", "financial_health_score",
        "geographic_risk_score", "contract_status",
    },
    "parts": {
        "part_id", "part_name", "category", "criticality", "supplier_id", "unit_cost",
    },
    "purchase_orders": {
        "po_id", "supplier_id", "part_id", "order_date", "promised_date", "receipt_date",
        "quantity", "unit_price", "defect_quantity", "status",
    },
    "inventory": {
        "part_id", "on_hand_units", "daily_demand_units", "safety_stock_units",
    },
}


def load_data(data_dir: str | Path) -> dict[str, pd.DataFrame]:
    data_dir = Path(data_dir)
    tables = {
        name: pd.read_csv(data_dir / f"{name}.csv")
        for name in REQUIRED_COLUMNS
    }
    for column in ("order_date", "promised_date", "receipt_date"):
        tables["purchase_orders"][column] = pd.to_datetime(
            tables["purchase_orders"][column], errors="coerce"
        )
    validate_data(tables)
    return tables


def validate_data(tables: Mapping[str, pd.DataFrame]) -> None:
    for table_name, required in REQUIRED_COLUMNS.items():
        if table_name not in tables:
            raise ValueError(f"Missing table: {table_name}")
        missing = required.difference(tables[table_name].columns)
        if missing:
            raise ValueError(f"{table_name} is missing columns: {sorted(missing)}")

    unique_keys = {
        "suppliers": ["supplier_id"],
        "purchase_orders": ["po_id"],
        "inventory": ["part_id"],
    }
    for table_name, keys in unique_keys.items():
        if tables[table_name].duplicated(keys).any():
            raise ValueError(f"{table_name} contains duplicate keys: {keys}")

    po = tables["purchase_orders"]
    if (po["quantity"] <= 0).any() or (po["unit_price"] < 0).any():
        raise ValueError("Purchase-order quantity and price must be valid non-negative values")
    if (po["defect_quantity"] < 0).any() or (po["defect_quantity"] > po["quantity"]).any():
        raise ValueError("Defect quantity must be between zero and ordered quantity")


def _minmax(series: pd.Series, neutral: float = 50.0) -> pd.Series:
    values = series.astype(float)
    spread = values.max() - values.min()
    if pd.isna(spread) or spread == 0:
        return pd.Series(neutral, index=series.index, dtype=float)
    return 100 * (values - values.min()) / spread


def calculate_supplier_scores(tables: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    suppliers = tables["suppliers"].copy()
    parts = tables["parts"].copy()
    po = tables["purchase_orders"].copy()

    po["late_days"] = (po["receipt_date"] - po["promised_date"]).dt.days.clip(lower=0)
    po["is_on_time"] = po["late_days"].eq(0)
    po["actual_lead_time_days"] = (po["receipt_date"] - po["order_date"]).dt.days
    po["line_value"] = po["quantity"] * po["unit_price"]

    performance = po.groupby("supplier_id", as_index=False).agg(
        po_lines=("po_id", "count"),
        spend=("line_value", "sum"),
        on_time_delivery_rate=("is_on_time", "mean"),
        average_late_days=("late_days", "mean"),
        defect_units=("defect_quantity", "sum"),
        received_units=("quantity", "sum"),
        average_lead_time_days=("actual_lead_time_days", "mean"),
        lead_time_std_days=("actual_lead_time_days", "std"),
    )
    performance["defect_rate"] = (
        performance["defect_units"] / performance["received_units"].replace(0, np.nan)
    ).fillna(0)
    performance["lead_time_cv"] = (
        performance["lead_time_std_days"]
        / performance["average_lead_time_days"].replace(0, np.nan)
    ).fillna(0)

    supplier_counts = parts.groupby("part_id")["supplier_id"].nunique().rename("supplier_count")
    dependency = parts.join(supplier_counts, on="part_id")
    dependency["single_source"] = dependency["supplier_count"].eq(1)
    dependency["critical_part"] = dependency["criticality"].eq("Critical")
    dependency["dependency_points"] = (
        70 * dependency["single_source"].astype(int)
        + 30 * dependency["critical_part"].astype(int)
    )
    dependency_summary = dependency.groupby("supplier_id", as_index=False).agg(
        supplied_parts=("part_id", "nunique"),
        single_source_parts=("single_source", "sum"),
        critical_parts=("critical_part", "sum"),
        dependency_risk=("dependency_points", "mean"),
    )

    scored = suppliers.merge(performance, on="supplier_id", how="left").merge(
        dependency_summary, on="supplier_id", how="left"
    )
    scored["delivery_risk"] = (1 - scored["on_time_delivery_rate"].fillna(0)) * 100
    scored["quality_risk"] = (scored["defect_rate"].fillna(0) * 2000).clip(0, 100)
    scored["lead_time_variability_risk"] = _minmax(scored["lead_time_cv"].fillna(0))
    scored["geographic_risk"] = scored["geographic_risk_score"].clip(0, 100)
    scored["financial_risk"] = (100 - scored["financial_health_score"]).clip(0, 100)
    scored["dependency_risk"] = scored["dependency_risk"].fillna(0).clip(0, 100)

    scored["risk_score"] = sum(scored[component] * weight for component, weight in RISK_WEIGHTS.items())
    scored["risk_score"] = scored["risk_score"].round(1).clip(0, 100)
    scored["risk_tier"] = pd.cut(
        scored["risk_score"],
        bins=[-0.01, MEDIUM_RISK_THRESHOLD, HIGH_RISK_THRESHOLD, 100],
        labels=["Low", "Medium", "High"],
    ).astype(str)
    return scored.sort_values("risk_score", ascending=False).reset_index(drop=True)


def apply_weight_scenario(
    supplier_scores: pd.DataFrame, weights: Mapping[str, float]
) -> pd.DataFrame:
    """Recalculate supplier scores and rankings under a normalized weight scenario."""
    missing = set(RISK_WEIGHTS).difference(weights)
    if missing:
        raise ValueError(f"Scenario is missing risk weights: {sorted(missing)}")
    if any(float(weights[name]) < 0 for name in RISK_WEIGHTS):
        raise ValueError("Risk weights cannot be negative")

    total = sum(float(weights[name]) for name in RISK_WEIGHTS)
    if total <= 0:
        raise ValueError("At least one risk weight must be greater than zero")
    normalized = {name: float(weights[name]) / total for name in RISK_WEIGHTS}

    scenario = supplier_scores.copy()
    scenario["baseline_rank"] = scenario["risk_score"].rank(
        method="min", ascending=False
    ).astype(int)
    scenario["scenario_score"] = sum(
        scenario[component] * weight for component, weight in normalized.items()
    ).round(1).clip(0, 100)
    scenario["scenario_rank"] = scenario["scenario_score"].rank(
        method="min", ascending=False
    ).astype(int)
    scenario["rank_change"] = scenario["baseline_rank"] - scenario["scenario_rank"]
    scenario["scenario_risk_tier"] = pd.cut(
        scenario["scenario_score"],
        bins=[-0.01, MEDIUM_RISK_THRESHOLD, HIGH_RISK_THRESHOLD, 100],
        labels=["Low", "Medium", "High"],
    ).astype(str)
    scenario["tier_changed"] = scenario["risk_tier"] != scenario["scenario_risk_tier"]
    return scenario.sort_values(
        ["scenario_rank", "supplier_id"], ascending=[True, True]
    ).reset_index(drop=True)


def calculate_part_risk(
    tables: Mapping[str, pd.DataFrame], supplier_scores: pd.DataFrame
) -> pd.DataFrame:
    parts = tables["parts"].copy()
    inventory = tables["inventory"].copy()
    supplier_counts = parts.groupby("part_id")["supplier_id"].nunique().rename("supplier_count")
    risk_lookup = supplier_scores.set_index("supplier_id")["risk_score"]
    parts["supplier_risk_score"] = parts["supplier_id"].map(risk_lookup)

    part_summary = parts.groupby(
        ["part_id", "part_name", "category", "criticality"], as_index=False
    ).agg(
        supplier_count=("supplier_id", "nunique"),
        max_supplier_risk=("supplier_risk_score", "max"),
        average_unit_cost=("unit_cost", "mean"),
    )
    part_summary = part_summary.merge(inventory, on="part_id", how="left")

    po = tables["purchase_orders"].copy()
    po["lead_time_days"] = (po["receipt_date"] - po["order_date"]).dt.days
    lead_time = po.groupby("part_id")["lead_time_days"].mean().rename("average_lead_time_days")
    part_summary = part_summary.join(lead_time, on="part_id")
    part_summary["days_of_supply"] = (
        part_summary["on_hand_units"]
        / part_summary["daily_demand_units"].replace(0, np.nan)
    ).fillna(np.inf)
    part_summary["single_source"] = part_summary["supplier_count"].eq(1)
    part_summary["stockout_risk"] = (
        part_summary["days_of_supply"] < part_summary["average_lead_time_days"]
    )
    part_summary["critical_flag"] = part_summary["criticality"].eq("Critical")
    part_summary["part_risk_score"] = (
        0.45 * part_summary["max_supplier_risk"].fillna(0)
        + 25 * part_summary["single_source"].astype(int)
        + 20 * part_summary["stockout_risk"].astype(int)
        + 10 * part_summary["critical_flag"].astype(int)
    ).clip(0, 100).round(1)
    part_summary["recommended_action"] = np.select(
        [
            part_summary["stockout_risk"] & part_summary["critical_flag"],
            part_summary["single_source"] & part_summary["critical_flag"],
            part_summary["part_risk_score"].ge(65),
        ],
        ["Expedite and allocate", "Qualify a second source", "Supplier mitigation plan"],
        default="Monitor",
    )
    return part_summary.sort_values("part_risk_score", ascending=False).reset_index(drop=True)


def calculate_kpis(
    tables: Mapping[str, pd.DataFrame], supplier_scores: pd.DataFrame, part_risk: pd.DataFrame
) -> dict[str, float | int]:
    po = tables["purchase_orders"].copy()
    po["line_value"] = po["quantity"] * po["unit_price"]
    high_risk_ids = set(
        supplier_scores.loc[supplier_scores["risk_score"] >= HIGH_RISK_THRESHOLD, "supplier_id"]
    )
    critical_part_ids = set(part_risk.loc[part_risk["critical_flag"], "part_id"])
    exposed = po[po["supplier_id"].isin(high_risk_ids) | po["part_id"].isin(critical_part_ids)]
    on_time = (po["receipt_date"] <= po["promised_date"]).mean()
    return {
        "high_risk_suppliers": int(
            (supplier_scores["risk_score"] >= HIGH_RISK_THRESHOLD).sum()
        ),
        "critical_spend_exposed": float(exposed["line_value"].sum()),
        "single_source_parts": int(part_risk["single_source"].sum()),
        "potential_stockouts": int(part_risk["stockout_risk"].sum()),
        "on_time_delivery_rate": float(on_time),
    }


def build_analysis(data_dir: str | Path) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.DataFrame, dict]:
    tables = load_data(data_dir)
    supplier_scores = calculate_supplier_scores(tables)
    part_risk = calculate_part_risk(tables, supplier_scores)
    kpis = calculate_kpis(tables, supplier_scores, part_risk)
    return tables, supplier_scores, part_risk, kpis

