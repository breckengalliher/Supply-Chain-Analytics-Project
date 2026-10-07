from pathlib import Path
import unittest

import pandas as pd

from src.supply_chain_risk.analytics import (
    RISK_WEIGHTS,
    apply_weight_scenario,
    build_analysis,
    calculate_supplier_scores,
    load_data,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "raw"


class AnalyticsTests(unittest.TestCase):
    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(RISK_WEIGHTS.values()), 1.0)

    def test_generated_data_loads_and_keys_are_unique(self):
        tables = load_data(DATA_DIR)
        self.assertTrue(tables["suppliers"]["supplier_id"].is_unique)
        self.assertTrue(tables["purchase_orders"]["po_id"].is_unique)
        self.assertTrue(tables["inventory"]["part_id"].is_unique)

    def test_scores_are_bounded_and_ranked(self):
        tables = load_data(DATA_DIR)
        scores = calculate_supplier_scores(tables)
        self.assertTrue(scores["risk_score"].between(0, 100).all())
        self.assertTrue(scores["risk_score"].is_monotonic_decreasing)
        self.assertTrue(set(scores["risk_tier"]).issubset({"Low", "Medium", "High"}))

    def test_analysis_outputs_are_actionable(self):
        _, scores, parts, kpis = build_analysis(DATA_DIR)
        self.assertEqual(len(scores), 40)
        self.assertEqual(len(parts), 90)
        self.assertTrue(parts["recommended_action"].notna().all())
        self.assertTrue(0 <= kpis["on_time_delivery_rate"] <= 1)
        self.assertGreater(kpis["critical_spend_exposed"], 0)

    def test_higher_delivery_failure_increases_score(self):
        tables = load_data(DATA_DIR)
        base = calculate_supplier_scores(tables).set_index("supplier_id")
        target = base.index[0]
        modified = {name: frame.copy() for name, frame in tables.items()}
        mask = modified["purchase_orders"]["supplier_id"].eq(target)
        modified["purchase_orders"].loc[mask, "receipt_date"] = (
            modified["purchase_orders"].loc[mask, "promised_date"] + pd.Timedelta(days=60)
        )
        changed = calculate_supplier_scores(modified).set_index("supplier_id")
        self.assertGreaterEqual(
            changed.loc[target, "delivery_risk"], base.loc[target, "delivery_risk"]
        )

    def test_weight_scenario_normalizes_and_ranks(self):
        tables = load_data(DATA_DIR)
        scores = calculate_supplier_scores(tables)
        scenario = apply_weight_scenario(
            scores,
            {
                "delivery_risk": 60,
                "quality_risk": 10,
                "lead_time_variability_risk": 10,
                "geographic_risk": 10,
                "financial_risk": 5,
                "dependency_risk": 5,
            },
        )
        self.assertTrue(scenario["scenario_score"].between(0, 100).all())
        self.assertEqual(scenario["scenario_rank"].min(), 1)
        self.assertTrue(scenario["scenario_rank"].is_monotonic_increasing)
        self.assertTrue((scenario["scenario_score"] != scenario["risk_score"]).any())

    def test_weight_scenario_rejects_zero_total(self):
        tables = load_data(DATA_DIR)
        scores = calculate_supplier_scores(tables)
        with self.assertRaises(ValueError):
            apply_weight_scenario(scores, {component: 0 for component in RISK_WEIGHTS})


if __name__ == "__main__":
    unittest.main()

