"""Known-answer and leakage tests for pit_walk_forward feature construction."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pit_walk_forward as pw  # noqa: E402


def frame(n=300, seed=0, scale=1.0):
    rng = np.random.default_rng(seed)
    c = 50 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    o = c * (1 + rng.normal(0, 0.005, n))
    a = pd.DataFrame({"AdjOpen": o, "AdjHigh": np.maximum(o, c) * 1.01, "AdjLow": np.minimum(o, c) * 0.99,
                      "AdjClose": c, "AdjVolume": rng.uniform(1e6, 2e6, n)}, index=pd.bdate_range("2012-01-02", periods=n))
    a["TrClose"] = a["AdjClose"] * 1.0001 ** np.arange(n)
    for k in ["AdjOpen", "AdjHigh", "AdjLow", "AdjClose", "TrClose"]:
        a[k] *= scale
    a["AdjVolume"] /= scale
    return a


STOCK_FEATS = [f for f in pw.FEATURES if not f.startswith("spy_")]


def test_features_are_causal():
    a = frame()
    base = pw.security_features(a)
    b = a.copy()
    b.iloc[250:, :] *= 1.7                        # change the future only
    alt = pw.security_features(b)
    pd.testing.assert_frame_equal(base.iloc[:250][STOCK_FEATS], alt.iloc[:250][STOCK_FEATS])


def test_features_are_scale_invariant():
    # adjusted levels embed later splits, so a constant rescale must not change any feature or label
    x, y = pw.security_features(frame()), pw.security_features(frame(scale=4.0))
    cols = STOCK_FEATS + [f"Target_{h}" for h in pw.HORIZONS]
    np.testing.assert_allclose(x[cols].to_numpy(), y[cols].to_numpy(), rtol=1e-9, atol=1e-9, equal_nan=True)


def test_labels_are_forward_tr_log_returns_and_end_nan():
    a = frame()
    d = pw.security_features(a)
    tr = a["TrClose"].to_numpy()
    assert d["Target_1w"].iloc[10] == pytest.approx(np.log(tr[15] / tr[10]))
    assert d["Target_6m"].iloc[:-126].notna().all() and d["Target_6m"].iloc[-126:].isna().all()


def test_known_values():
    a = frame()
    d = pw.security_features(a)
    c = a["AdjClose"]
    assert d["MA10"].iloc[20] == pytest.approx(c.iloc[11:21].mean() / c.iloc[20] - 1)
    assert d["YesterdayCloseLogR"].iloc[5] == pytest.approx(np.log(c.iloc[5] / c.iloc[4]))
    assert set(pw.FEATURES) == set(d.columns.drop([f"Target_{h}" for h in pw.HORIZONS])) | \
        {"spy_ret_1d", "spy_ret_5d", "spy_ret_20d", "spy_vol_20d"}


def test_spy_features():
    s = pd.DataFrame({"tr_index": [1.0, 1.01, 1.0201]}, index=pd.bdate_range("2012-01-02", periods=3))
    f = pw.spy_features(s)
    assert f["spy_ret_1d"].iloc[2] == pytest.approx(np.log(1.01))
