from __future__ import annotations

import ast
import contextlib
import io
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_DIR = ROOT / "notebooks"
sys.path.insert(0, str(ROOT))


def markdown(source: str) -> dict[str, Any]:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


def code(source: str) -> dict[str, Any]:
    return {
        "cell_type": "code", "execution_count": None, "metadata": {},
        "outputs": [], "source": source.splitlines(keepends=True),
    }


def notebook(cells: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.10+"},
        },
        "nbformat": 4, "nbformat_minor": 5,
    }


def render_result(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "_repr_html_"):
        html = value._repr_html_()
        if html:
            return {"output_type": "execute_result", "data": {"text/html": html, "text/plain": repr(value)}, "metadata": {}}
    return {"output_type": "execute_result", "data": {"text/plain": repr(value)}, "metadata": {}}


def execute_notebook(document: dict[str, Any]) -> None:
    namespace: dict[str, Any] = {"__name__": "__main__"}
    execution_count = 0
    for cell in document["cells"]:
        if cell["cell_type"] != "code":
            continue
        execution_count += 1
        parsed = ast.parse("".join(cell["source"]))
        result = None
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            if parsed.body and isinstance(parsed.body[-1], ast.Expr):
                exec(compile(ast.Module(body=parsed.body[:-1], type_ignores=[]), "<notebook>", "exec"), namespace)
                result = eval(compile(ast.Expression(parsed.body[-1].value), "<notebook>", "eval"), namespace)
            else:
                exec(compile(parsed, "<notebook>", "exec"), namespace)
        outputs = []
        if stdout.getvalue():
            outputs.append({"output_type": "stream", "name": "stdout", "text": stdout.getvalue()})
        rendered = render_result(result)
        if rendered:
            rendered["execution_count"] = execution_count
            outputs.append(rendered)
        cell["execution_count"] = execution_count
        cell["outputs"] = outputs


SETUP = """from pathlib import Path
import pandas as pd

from src.supply_chain_risk.analytics import RISK_WEIGHTS, apply_weight_scenario, build_analysis, load_data

ROOT = Path.cwd()
DATA_DIR = ROOT / "data" / "raw"
tables, supplier_scores, part_risk, kpis = build_analysis(DATA_DIR)
pd.set_option("display.max_columns", 20)
pd.set_option("display.float_format", lambda value: f"{value:,.2f}")
"""


NOTEBOOKS = {
    "01_data_quality.ipynb": notebook([
        markdown("""# 01 — Data Quality & Readiness

## tl;dr

The synthetic source contains **40 suppliers, 90 unique parts, and 1,800 purchase-order lines**. Required primary keys are unique, mandatory analytical fields are populated, PO quantities and defect counts pass validity checks, and every PO maps to a known supplier and part. The dataset is ready for the portfolio analysis, with the important caveat that synthetic completeness does not represent the messiness of a production ERP system."""),
        markdown("""## Context & Methods

Before supplier scores can support a decision, we need to establish whether the underlying records are complete, unique, valid, and joinable.

### Key Assumptions

- Each purchase-order row represents one received PO line.
- `supplier_id`, `po_id`, and inventory `part_id` are expected to be unique at their stated grain.
- Dates use a common calendar and quantities are expressed in units.
- The generated data is a controlled demonstration, not a live ERP extract."""),
        markdown("### 1. Load the source tables"),
        code(SETUP + "\n{name: frame.shape for name, frame in tables.items()}"),
        markdown("### 2. Inspect a bounded record sample"),
        code("tables['purchase_orders'].head(8)"),
        markdown("### 3. Test completeness, uniqueness, validity, and joins"),
        code("""quality_rows = []
for name, frame in tables.items():
    quality_rows.append({"table": name, "rows": len(frame), "columns": len(frame.columns), "missing_required_values": int(frame.isna().sum().sum())})
quality_summary = pd.DataFrame(quality_rows)
quality_summary["duplicate_primary_keys"] = [
    tables["suppliers"].duplicated("supplier_id").sum(),
    tables["parts"].duplicated(["part_id", "supplier_id"]).sum(),
    tables["purchase_orders"].duplicated("po_id").sum(),
    tables["inventory"].duplicated("part_id").sum(),
]
quality_summary["status"] = quality_summary.apply(lambda row: "Pass" if row["missing_required_values"] == 0 and row["duplicate_primary_keys"] == 0 else "Review", axis=1)
quality_summary"""),
        markdown("### 4. Verify relational coverage and business rules"),
        code("""po = tables["purchase_orders"]
checks = pd.DataFrame([
    {"check": "POs with unknown supplier", "exceptions": int((~po["supplier_id"].isin(set(tables["suppliers"]["supplier_id"]))).sum())},
    {"check": "POs with unknown part", "exceptions": int((~po["part_id"].isin(set(tables["parts"]["part_id"]))).sum())},
    {"check": "Non-positive PO quantities", "exceptions": int((po["quantity"] <= 0).sum())},
    {"check": "Defects exceeding quantity", "exceptions": int((po["defect_quantity"] > po["quantity"]).sum())},
    {"check": "Receipt before order date", "exceptions": int((po["receipt_date"] < po["order_date"]).sum())},
])
checks["status"] = checks["exceptions"].map(lambda value: "Pass" if value == 0 else "Review")
checks"""),
        markdown("""## Results

The controlled dataset passes the checks needed for the current analysis. The clean result is expected because the generator deliberately enforces valid keys and ranges. In production, the same checks would produce an exception table for remediation rather than silently dropping records.

## Takeaways

- Table grains and keys are explicit and testable.
- Supplier and part joins preserve the intended population.
- Management metrics are calculated only after validation.
- A real implementation would add data owners, refresh checks, rejected-row logging, currency normalization, and ERP reconciliation."""),
    ]),
    "02_supplier_performance.ipynb": notebook([
        markdown("""# 02 — Supplier Performance

## tl;dr

Across **1,800 PO lines**, on-time delivery is **83.4%**. Performance varies materially by supplier, and the highest spend does not automatically imply the highest operational risk. This notebook separates historical supplier performance from dependency and consequence."""),
        markdown("""## Context & Methods

This analysis asks: **How have suppliers performed over the observed 12-month purchasing period?** We summarize delivery, lateness, defects, lead-time consistency, and spend at the supplier grain.

### Key Assumptions

- A line is on time when receipt is on or before its promised date.
- Defect rate uses received quantity as the denominator.
- PO value equals ordered quantity multiplied by unit price.
- The analysis describes association and performance; it does not prove why a supplier was late or defective."""),
        markdown("### 1. Load validated analytical outputs"),
        code(SETUP + "\nsupplier_scores.shape"),
        markdown("### 2. Review portfolio-level performance"),
        code("""pd.DataFrame([
    {"measure": "Supplier count", "value": len(supplier_scores)},
    {"measure": "PO-line count", "value": len(tables["purchase_orders"])},
    {"measure": "On-time delivery rate", "value": f"{kpis['on_time_delivery_rate']:.1%}"},
    {"measure": "Total PO value", "value": f"${supplier_scores['spend'].sum():,.0f}"},
])"""),
        markdown("### 3. Compare suppliers using consistent definitions"),
        code("""performance_columns = ["supplier_name", "country", "po_lines", "spend", "on_time_delivery_rate", "average_late_days", "defect_rate", "average_lead_time_days", "lead_time_cv"]
supplier_scores[performance_columns].sort_values(["on_time_delivery_rate", "defect_rate"], ascending=[True, False]).head(12).round(3)"""),
        markdown("### 4. Compare performance with commercial exposure"),
        code("""supplier_scores.nlargest(10, "spend")[["supplier_name", "spend", "on_time_delivery_rate", "defect_rate", "risk_score"]].round(3)"""),
        markdown("""## Results

Performance measures reveal different supplier behaviors: some suppliers have weaker delivery reliability, others have higher quality losses, and high-spend suppliers are not uniformly the highest risk.

## Takeaways

- Review delivery, quality, lead-time stability, and spend together.
- Avoid ranking suppliers using one KPI alone.
- Investigate root causes before treating performance associations as causal.
- Use the next notebook to combine performance with dependency and consequence."""),
    ]),
    "03_supplier_risk.ipynb": notebook([
        markdown("""# 03 — Supplier Risk Model

## tl;dr

The baseline model identifies **4 high-risk suppliers** using an explainable weighted score. The model combines observed performance with geographic, financial, and sourcing-dependency exposure. Scores prioritize investigation; they are not predictions of supplier failure."""),
        markdown("""## Context & Methods

This notebook asks: **Which suppliers deserve management attention when performance, exposure, and dependency are considered together?**

### Key Assumptions

- The six weights represent a hypothetical management risk appetite.
- Component scores are normalized to a 0–100 scale.
- A score of 35 or more is high risk for this synthetic portfolio.
- The result is a prioritization model, not a causal or probabilistic forecast."""),
        markdown("### 1. Load scores and inspect model weights"),
        code(SETUP + "\npd.Series(RISK_WEIGHTS, name='weight').rename_axis('component').to_frame()"),
        markdown("### 2. Review the highest baseline supplier risks"),
        code("""risk_columns = ["supplier_name", "country", "risk_tier", "risk_score", "delivery_risk", "quality_risk", "lead_time_variability_risk", "geographic_risk", "financial_risk", "dependency_risk"]
supplier_scores[risk_columns].head(12).round(1)"""),
        markdown("### 3. Reconcile the weighted score for the top supplier"),
        code("""top_supplier = supplier_scores.iloc[0]
reconciliation = pd.DataFrame([{"component": component, "component_score": top_supplier[component], "weight": weight, "weighted_points": top_supplier[component] * weight} for component, weight in RISK_WEIGHTS.items()])
reconciliation.loc[len(reconciliation)] = {"component": "Total", "component_score": pd.NA, "weight": reconciliation["weight"].sum(), "weighted_points": reconciliation["weighted_points"].sum()}
reconciliation.round(3)"""),
        markdown("### 4. Inspect the risk-tier distribution"),
        code("""supplier_scores.groupby("risk_tier", observed=True).agg(suppliers=("supplier_id", "count"), spend=("spend", "sum"), average_score=("risk_score", "mean")).reindex(["High", "Medium", "Low"]).round(1)"""),
        markdown("""## Results

The model surfaces a small high-risk group while retaining the component evidence needed to challenge each score. Reconciliation confirms that the headline score equals the sum of weighted component points, subject only to display rounding.

## Takeaways

- Explainability is more useful than a black-box ranking for supplier reviews.
- High scores indicate where to investigate, not proof that disruption will occur.
- Thresholds and weights should be owned and calibrated by the business.
- Sensitivity testing is required before treating the ordering as robust."""),
    ]),
    "04_decision_support.ipynb": notebook([
        markdown("""# 04 — Decision Support

## tl;dr

The analysis flags **37 single-source parts**, **40 potential stockouts**, and **13 parts requiring immediate mitigation**. Of those actions, 11 are `Expedite and allocate` and 2 are `Qualify a second source`. Recommendations are deterministic responses to visible conditions—not automated purchasing decisions."""),
        markdown("""## Context & Methods

This notebook asks: **How should management translate supplier and inventory risk into an ordered action queue?** It combines part criticality, sourcing concentration, supplier risk, days of supply, and replenishment lead time.

### Key Assumptions

- Potential stockout means days of supply are below average historical replenishment lead time.
- Single-source status is based only on the suppliers present in the synthetic part map.
- Actions are triage rules and require buyer or planner review before execution."""),
        markdown("### 1. Load part-level decision data"),
        code(SETUP + "\npart_risk.shape"),
        markdown("### 2. Summarize exposure and proposed actions"),
        code("""pd.DataFrame([
    {"measure": "Single-source parts", "value": kpis["single_source_parts"]},
    {"measure": "Potential stockouts", "value": kpis["potential_stockouts"]},
    {"measure": "Critical spend exposed", "value": f"${kpis['critical_spend_exposed']:,.0f}"},
    {"measure": "Parts requiring immediate mitigation", "value": int((part_risk["recommended_action"] != "Monitor").sum())},
])"""),
        markdown("### 3. Review the action queue and supporting evidence"),
        code("""action_queue = part_risk[part_risk["recommended_action"] != "Monitor"][["part_id", "part_name", "category", "criticality", "supplier_count", "days_of_supply", "average_lead_time_days", "max_supplier_risk", "part_risk_score", "recommended_action"]].copy()
action_queue.head(20).round(1)"""),
        markdown("### 4. Confirm that actions follow the stated rules"),
        code("""pd.DataFrame({
    "Expedite rule violations": [int(((part_risk["recommended_action"] == "Expedite and allocate") & ~(part_risk["stockout_risk"] & part_risk["critical_flag"])).sum())],
    "Dual-source rule violations": [int(((part_risk["recommended_action"] == "Qualify a second source") & ~(part_risk["single_source"] & part_risk["critical_flag"])).sum())],
})"""),
        markdown("""## Results

The action queue prioritizes critical parts that may run out before replenishment, followed by critical single-source items. Rule checks confirm that proposed actions match documented conditions.

## Takeaways

- Evidence is preserved next to each recommendation.
- Buyers can distinguish immediate inventory intervention from longer-term sourcing work.
- Rules support consistent triage but do not replace planner judgment.
- Production use would add program impact, supplier capacity, mitigation cost, and action ownership."""),
    ]),
    "05_sensitivity_analysis.ipynb": notebook([
        markdown("""# 05 — Weight Sensitivity Analysis

## tl;dr

When delivery risk is increased to 60% of the model, the full supplier ranking retains a **0.91 Spearman correlation** with the baseline, but **10 suppliers change risk tiers**. The overall ordering is fairly stable, while threshold-based actions for borderline suppliers remain sensitive to management priorities."""),
        markdown("""## Context & Methods

This notebook asks: **Would management reach similar priorities under a different but plausible set of risk weights?** We compare the baseline model with a delivery-focused scenario.

### Key Assumptions

- Scenario inputs are normalized to 100%.
- Spearman correlation measures ordering similarity, not model accuracy.
- Tier changes identify decisions that require additional judgment.
- One scenario cannot establish universal robustness."""),
        markdown("### 1. Load baseline scores and define a scenario"),
        code(SETUP + "\nscenario_weights = {'delivery_risk': 60, 'quality_risk': 10, 'lead_time_variability_risk': 10, 'geographic_risk': 10, 'financial_risk': 5, 'dependency_risk': 5}\nscenario_weights"),
        markdown("### 2. Recalculate scores and measure stability"),
        code("""scenario = apply_weight_scenario(supplier_scores, scenario_weights)
baseline_top10 = set(supplier_scores.nlargest(10, "risk_score")["supplier_id"])
scenario_top10 = set(scenario.nsmallest(10, "scenario_rank")["supplier_id"])
pd.DataFrame([
    {"measure": "Top-10 suppliers retained", "value": f"{len(baseline_top10 & scenario_top10)}/10"},
    {"measure": "Spearman rank correlation", "value": f"{scenario[['baseline_rank', 'scenario_rank']].corr(method='spearman').iloc[0, 1]:.3f}"},
    {"measure": "Suppliers changing risk tier", "value": int(scenario["tier_changed"].sum())},
])"""),
        markdown("### 3. Inspect suppliers most affected by the assumption change"),
        code("""movers = scenario.assign(abs_rank_change=scenario["rank_change"].abs()).nlargest(12, "abs_rank_change")
movers[["supplier_name", "baseline_rank", "scenario_rank", "rank_change", "risk_score", "scenario_score", "risk_tier", "scenario_risk_tier"]].round(1)"""),
        markdown("### 4. Identify threshold-sensitive suppliers"),
        code("""scenario.loc[scenario["tier_changed"], ["supplier_name", "risk_score", "scenario_score", "risk_tier", "scenario_risk_tier"]].sort_values("scenario_score", ascending=False)"""),
        markdown("""## Results

The delivery-focused scenario preserves most of the overall ordering, but several suppliers cross portfolio risk thresholds. Those threshold-sensitive suppliers should be reviewed with additional evidence rather than treated as automatic escalations or removals.

## Takeaways

- Ranking stability and tier stability are different questions.
- Sensitivity analysis exposes where subjective assumptions affect decisions.
- Robust suppliers remain priorities across scenarios.
- Borderline suppliers require more evidence, calibrated thresholds, and business-owner review."""),
    ]),
}


def main() -> None:
    NOTEBOOK_DIR.mkdir(parents=True, exist_ok=True)
    for filename, document in NOTEBOOKS.items():
        execute_notebook(document)
        target = NOTEBOOK_DIR / filename
        target.write_text(json.dumps(document, indent=1), encoding="utf-8")
        print(f"Built and executed {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
