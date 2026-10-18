from __future__ import annotations

import pytest

from eval.metrics import EvalReport, FieldStats, ingredient_f1


def test_field_stats_exact_close_missing_hallucinated():
    s = FieldStats()
    s.add(30.0, 30.0)  # exact
    s.add(31.0, 30.0)  # within 5 %
    s.add(40.0, 30.0)  # wrong
    s.add(None, 30.0)  # missing
    s.add(1.0, None)  # hallucinated
    s.add(None, None)  # correctly absent
    assert (s.total, s.exact, s.close, s.missing) == (4, 1, 2, 1)
    assert (s.absent_cases, s.hallucinated) == (2, 1)


def test_ingredient_f1_ignores_case_percent_and_parent():
    assert ingredient_f1(["Sugar", "Palm Oil (12%)"], ["sugar", "palm oil"]) == 1.0
    assert ingredient_f1(["Filling > sugar"], ["sugar"]) == 1.0
    assert ingredient_f1(["sugar"], ["sugar", "salt"]) == pytest.approx(2 / 3)
    assert ingredient_f1([], []) == 1.0
    assert ingredient_f1([], ["salt"]) == 0.0


def test_report_summary():
    r = EvalReport()
    r.cases = 2
    r.failures = 1
    r.add_nutrition({"sugars_g": 30.0, "salt_g": 1.0}, {"sugars_g": 30.0, "salt_g": 0.5})
    r.latencies_ms += [1000, 3000]
    r.costs_usd += [0.02, 0.04]
    s = r.summary()
    assert s["numeric_exact_accuracy"] == 0.5
    assert s["failure_rate"] == 0.5
    assert s["latency_p95_ms"] == 3000
    assert s["cost_per_scan_usd"] == 0.03
