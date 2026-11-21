"""Unit tests for pit_evaluate helpers (synthetic data only; no study results are read)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pit_evaluate as pe  # noqa: E402


def test_pick_cutoff_rules():
    assert pe.pick_cutoff({0.20: 0.5, 0.25: 0.4, 0.30: 0.9, 0.35: None}) == 0.30
    assert pe.pick_cutoff({0.20: 0.9, 0.25: 0.4, 0.30: 0.9, 0.35: 0.1}) == 0.25     # tie -> 0.25
    assert pe.pick_cutoff({0.20: None, 0.25: float("nan"), 0.30: None, 0.35: None}) == 0.25


def long_frame():
    rows = []
    for seed, p in [(0, 0.4), (1, 0.6)]:
        for d in pd.to_datetime(["2016-01-04", "2017-01-03"]):
            r = {"Year": d.year, "Seed": seed, "Date": d, "isin": "X"}
            for h in pe.HZ:
                r[f"Pred_Prob_{h}"], r[f"Pred_Prob_Std_{h}"] = p, 0.1
            rows.append(r)
    return pd.DataFrame(rows)


def test_ensemble_variance_rule():
    e = pe.ensemble(long_frame())
    r = e.iloc[0]
    assert r["Pred_Prob_1d"] == pytest.approx(0.5)
    assert r["Pred_Prob_Std_1d"] == pytest.approx(np.sqrt(0.01 + 0.01))      # within 0.1^2, across var 0.01


def test_shift_scores_equivalent_to_cutoff():
    e = pe.ensemble(long_frame())
    s = pe.shift_scores(e, {2016: 0.35, 2017: 0.20})
    d16 = s[s["Year"] == 2016].iloc[0]
    d17 = s[s["Year"] == 2017].iloc[0]
    assert d16["Pred_Prob_1m"] == pytest.approx(0.5 - 0.10) and d17["Pred_Prob_1m"] == pytest.approx(0.5 + 0.05)
    # adj > c  <=>  shifted_adj > 0.25
    for c, row in [(0.35, d16), (0.20, d17)]:
        adj = 0.5 - row["Pred_Prob_Std_1m"]
        assert (adj > c) == (row["Pred_Prob_1m"] - row["Pred_Prob_Std_1m"] > 0.25)


def test_paired_diff_ci_identical_series_is_zero():
    r = np.random.default_rng(0).normal(0.001, 0.01, 500)
    lo, hi = pe.paired_sr_diff_ci(r, r, 200, np.random.default_rng(1))
    assert lo == pytest.approx(0) and hi == pytest.approx(0)
    lo, hi = pe.paired_sr_diff_ci(r + 0.002, r, 200, np.random.default_rng(1))
    assert lo > 0
