from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SEED = 20261003


def generate(output_dir: Path = ROOT / "data" / "raw") -> None:
    rng = np.random.default_rng(SEED)
    output_dir.mkdir(parents=True, exist_ok=True)

    countries = [
        ("United States", "North America", 18),
        ("Canada", "North America", 15),
        ("Mexico", "North America", 32),
        ("Germany", "Europe", 20),
        ("United Kingdom", "Europe", 24),
        ("Poland", "Europe", 36),
        ("Japan", "Asia-Pacific", 22),
        ("South Korea", "Asia-Pacific", 30),
        ("India", "Asia-Pacific", 48),
        ("Malaysia", "Asia-Pacific", 44),
    ]
    supplier_rows = []
    for i in range(1, 41):
        country, region, base_geo_risk = countries[rng.integers(0, len(countries))]
        supplier_rows.append(
            {
                "supplier_id": f"SUP-{i:03d}",
                "supplier_name": f"{rng.choice(['Aero', 'Nova', 'Orion', 'Titan', 'Summit', 'Vector', 'Atlas', 'Pioneer'])} "
                f"{rng.choice(['Systems', 'Precision', 'Components', 'Materials', 'Dynamics'])} {i:02d}",
                "country": country,
                "region": region,
                "financial_health_score": int(np.clip(rng.normal(73, 15), 25, 98)),
                "geographic_risk_score": int(np.clip(base_geo_risk + rng.normal(0, 9), 5, 90)),
                "contract_status": rng.choice(["Active", "Active", "Active", "Under review"]),
            }
        )
    suppliers = pd.DataFrame(supplier_rows)

    categories = ["Avionics", "Propulsion", "Structures", "Electrical", "Interiors", "Fasteners"]
    criticality_levels = ["Critical", "High", "Standard"]
    part_rows = []
    for i in range(1, 91):
        category = categories[rng.integers(0, len(categories))]
        criticality = rng.choice(criticality_levels, p=[0.25, 0.35, 0.40])
        supplier_count = rng.choice([1, 2, 3], p=[0.44, 0.40, 0.16])
        selected = rng.choice(suppliers["supplier_id"], size=supplier_count, replace=False)
        base_cost = float(np.exp(rng.normal(5.3, 1.0)))
        for supplier_id in selected:
            part_rows.append(
                {
                    "part_id": f"PRT-{i:04d}",
                    "part_name": f"{category[:-1] if category.endswith('s') else category} Assembly {i:03d}",
                    "category": category,
                    "criticality": criticality,
                    "supplier_id": supplier_id,
                    "unit_cost": round(base_cost * rng.uniform(0.9, 1.12), 2),
                }
            )
    parts = pd.DataFrame(part_rows)

    inventory_rows = []
    for part_id, group in parts.groupby("part_id"):
        daily_demand = int(rng.integers(2, 28))
        days_cover = int(rng.integers(12, 110))
        inventory_rows.append(
            {
                "part_id": part_id,
                "on_hand_units": daily_demand * days_cover,
                "daily_demand_units": daily_demand,
                "safety_stock_units": daily_demand * int(rng.integers(10, 31)),
            }
        )
    inventory = pd.DataFrame(inventory_rows)

    supplier_behavior = suppliers.set_index("supplier_id").copy()
    supplier_behavior["late_probability"] = np.clip(
        0.08 + supplier_behavior["geographic_risk_score"] / 210 + rng.normal(0, 0.07, len(suppliers)),
        0.05,
        0.70,
    )
    supplier_behavior["defect_probability"] = np.clip(
        0.002 + (100 - supplier_behavior["financial_health_score"]) / 2400,
        0.002,
        0.045,
    )

    order_rows = []
    part_supplier_pairs = parts[["part_id", "supplier_id", "unit_cost"]].reset_index(drop=True)
    start = pd.Timestamp("2025-10-01")
    for i in range(1, 1801):
        pair = part_supplier_pairs.iloc[rng.integers(0, len(part_supplier_pairs))]
        supplier = supplier_behavior.loc[pair["supplier_id"]]
        order_date = start + pd.Timedelta(days=int(rng.integers(0, 365)))
        planned_lead = int(rng.integers(24, 86))
        promised_date = order_date + pd.Timedelta(days=planned_lead)
        if rng.random() < supplier["late_probability"]:
            late_days = int(rng.integers(2, 31))
        else:
            late_days = int(rng.integers(-8, 1))
        receipt_date = promised_date + pd.Timedelta(days=late_days)
        quantity = int(rng.integers(15, 420))
        defects = int(rng.binomial(quantity, supplier["defect_probability"]))
        order_rows.append(
            {
                "po_id": f"PO-{i:06d}",
                "supplier_id": pair["supplier_id"],
                "part_id": pair["part_id"],
                "order_date": order_date.date().isoformat(),
                "promised_date": promised_date.date().isoformat(),
                "receipt_date": receipt_date.date().isoformat(),
                "quantity": quantity,
                "unit_price": round(float(pair["unit_cost"] * rng.uniform(0.96, 1.08)), 2),
                "defect_quantity": defects,
                "status": "Received",
            }
        )
    purchase_orders = pd.DataFrame(order_rows)

    suppliers.to_csv(output_dir / "suppliers.csv", index=False)
    parts.to_csv(output_dir / "parts.csv", index=False)
    inventory.to_csv(output_dir / "inventory.csv", index=False)
    purchase_orders.to_csv(output_dir / "purchase_orders.csv", index=False)
    print(f"Generated synthetic data in {output_dir}")


if __name__ == "__main__":
    generate()

