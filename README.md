# Aerospace Supplier Risk & Resilience Dashboard

An end-to-end Python portfolio project that turns procurement, supplier, part, and inventory data into decisions for a fictional aerospace manufacturer.

> **Data note:** Every company, transaction, location, and result in this repository is synthetic. The project demonstrates analytical methods and does not describe a real supply chain.

## Business question

Which suppliers and critical parts should management address first to reduce disruption risk?

The project combines delivery reliability, quality, lead-time variability, geographic exposure, financial health, part criticality, sourcing concentration, and inventory coverage into an explainable 0–100 supplier risk score. It then converts the result into practical actions: monitor, supplier-development plan, dual-source, or expedite.

## What this demonstrates

- Reproducible synthetic-data generation
- Relational data modeling across suppliers, parts, purchase orders, and inventory
- Data validation and feature engineering with pandas
- Transparent KPI and supplier-risk definitions
- Interactive analysis with Streamlit and Plotly
- Weight-sensitivity analysis that tests ranking and risk-tier stability
- Unit tests for calculations and boundary conditions
- Version-control-ready project organization

## Dashboard measures

| Measure | Definition | Management use |
|---|---|---|
| High-risk suppliers | Suppliers scoring 35 or higher | Prioritize mitigation reviews |
| Critical spend exposed | Open PO value tied to high-risk suppliers or critical parts | Quantify financial exposure |
| Single-source parts | Parts mapped to exactly one supplier | Identify dual-source candidates |
| Potential stockouts | Parts with fewer days of supply than replenishment lead time | Trigger expedite or allocation action |
| On-time delivery | PO lines received on or before the promised date | Monitor service reliability |

## Risk model

The supplier score is intentionally transparent:

```text
30% delivery risk
20% quality risk
15% lead-time variability
15% geographic exposure
10% financial risk
10% dependency risk
```

Each component is normalized to 0–100. For this synthetic portfolio, scores below 25 are low risk, 25–34.9 are medium risk, and 35 or higher are high risk. The thresholds and weights represent a hypothetical risk appetite—not universal truths—and the dashboard exposes the component scores so reviewers can challenge them.

## Project structure

```text
app.py                         Interactive dashboard
scripts/generate_data.py       Deterministic synthetic data generator
scripts/build_notebooks.py     Rebuilds executed analytical notebooks
src/supply_chain_risk/
  analytics.py                 Validation, KPIs, scoring, and action logic
data/raw/                      Publishable synthetic source tables
data/processed/                Regenerated analytical outputs
notebooks/                     Five guided analysis notebooks
tests/                         Calculation and validation tests
```

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python scripts/generate_data.py
streamlit run app.py
```

Run the checks:

```bash
python -m unittest discover -s tests -v
```

Rebuild the executed notebooks after changing data or calculations:

```bash
python scripts/build_notebooks.py
```

The notebooks use only Python and pandas so they remain easy to run in minimal environments.

## Deploy to Streamlit Community Cloud

1. Push this repository to GitHub.
2. In Streamlit Community Cloud, choose **Create app**.
3. Select the repository and its `main` branch.
4. Set the entrypoint to `app.py`.
5. Deploy. Streamlit installs the packages in `requirements.txt` automatically.

The application does not require secrets or external data connections because all published data is synthetic and stored in the repository.

## Data model

- `suppliers.csv`: one row per supplier
- `parts.csv`: one row per supplier-part relationship
- `purchase_orders.csv`: one row per purchase-order line
- `inventory.csv`: one row per unique part

The analytical pipeline validates required columns and key uniqueness before joining the tables. Supplier performance is calculated from PO history; sourcing concentration and part criticality come from the part map; stockout flags compare inventory coverage with expected replenishment time.

## Decision robustness

The dashboard's weight sensitivity lab allows a reviewer to change the relative importance of delivery, quality, lead-time variability, geographic, financial, and dependency risk. Python normalizes the inputs, recalculates every supplier score, and reports:

- overlap between the baseline and scenario top-10 lists;
- Spearman rank correlation for the complete supplier ranking;
- suppliers that cross a risk-tier threshold; and
- the largest positive and negative ranking changes.

This distinguishes a robust sourcing recommendation from one that depends heavily on subjective model assumptions.

## Intended discussion points

This is a decision-support prototype. A production implementation would replace the synthetic CSVs with ERP, supplier-quality, logistics, and risk-intelligence feeds; establish metric ownership; calibrate weights against historical disruptions; add refresh monitoring; and enforce access controls.

