"""Known-answer tests for preclose_proxy.py."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import preclose_proxy as pc  # noqa: E402


def bars(times_utc, prices, bid=None, ask=None):
    df = pd.DataFrame({"TRDPRC_1": prices}, index=pd.DatetimeIndex(pd.to_datetime(times_utc)))
    if bid is not None:
        df["BID"], df["ASK"] = bid, ask
    return df


def test_snapshot_uses_1535_ny_bar_in_winter_and_summer():
    # 2026-01-15 (EST, UTC-5): 15:35 NY = 20:35 UTC.  2026-07-15 (EDT, UTC-4): 15:35 NY = 19:35 UTC.
    b = bars(["2026-01-15 20:30", "2026-01-15 20:35", "2026-01-15 20:40",
              "2026-07-15 19:30", "2026-07-15 19:35", "2026-07-15 19:40"],
             [10.0, 11.0, 99.0, 20.0, 21.0, 99.0], bid=[0, 10.9, 0, 0, 20.9, 0], ask=[0, 11.1, 0, 0, 21.1, 0])
    s = pc.snapshot_from_bars(b)
    assert s.loc["2026-01-15", "price"] == 11.0 and s.loc["2026-07-15", "price"] == 21.0   # never the 15:40 bar
    assert s.loc["2026-01-15", "label"] == "15:35"
    assert s.loc["2026-01-15", "bid"] == 10.9 and s.loc["2026-01-15", "ask"] == 11.1


def test_snapshot_falls_back_to_last_bar_after_1500_and_drops_otherwise():
    b = bars(["2026-01-15 20:10", "2026-01-15 20:20",          # 15:10, 15:20 NY; no 15:35 bar
              "2026-01-16 19:00",                              # 14:00 NY only -> dropped
              "2026-01-16 21:00"],                             # 16:00 NY (after the snapshot) -> ignored
             [5.0, 6.0, 7.0, 8.0])
    s = pc.snapshot_from_bars(b)
    assert s.loc["2026-01-15", "price"] == 6.0 and s.loc["2026-01-15", "label"] == "15:20"
    assert pd.Timestamp("2026-01-16") not in s.index


def test_basket_excess_hand_computed():
    d = pd.DatetimeIndex(["2026-01-05"])
    names = [f"S{i}" for i in range(20)]
    sig = pd.DataFrame([np.arange(20, dtype=float)], index=d, columns=names)   # S0, S1 are the 2 lowest
    ret = pd.DataFrame([np.r_[0.05, 0.03, np.zeros(18)]], index=d, columns=names)
    elig = pd.DataFrame(True, index=d, columns=names)
    cost = pd.DataFrame(0.001, index=d, columns=names)
    b = pc.basket_excess(sig, ret, elig, cost)
    r = b.iloc[0]
    assert r["k"] == 2 and set(r["names"]) == {"S0", "S1"}
    assert r["gross"] == pytest.approx(0.04 - 0.08 / 20)
    assert r["net"] == pytest.approx(r["gross"] - 0.001)
    top = pc.basket_excess(sig, ret, elig, bottom=False).iloc[0]
    assert set(top["names"]) == {"S18", "S19"} and top["gross"] == pytest.approx(-0.004)


def test_basket_needs_20_names():
    d = pd.DatetimeIndex(["2026-01-05"])
    x = pd.DataFrame([[1.0] * 19], index=d)
    assert pc.basket_excess(x, x, x.astype(bool)).empty


def test_variant_returns_restate_splits():
    d = pd.bdate_range("2026-01-05", periods=4)
    c = pd.DataFrame({"X": [100.0, 102.0, 51.5, 52.0]}, index=d)   # 2-for-1 effective on session 2
    o = pd.DataFrame({"X": [99.0, 101.0, 51.0, 52.5]}, index=d)
    f = pd.DataFrame({"X": [1.0, 1.0, 2.0, 1.0]}, index=d)
    r = pc.variant_returns(o, c, f)
    assert r["A"].iloc[0, 0] == pytest.approx(102 / 100 - 1)
    assert r["A"].iloc[1, 0] == pytest.approx(51.5 * 2 / 102 - 1)            # across the split
    assert r["B"].iloc[0, 0] == pytest.approx(51.0 * 2 / 101 - 1)            # open t+1 -> open t+2 across split
    assert r["C"].iloc[0, 0] == pytest.approx(51.5 * 2 / 102 - 1)
    assert r["D"].equals(r["A"])
    assert np.isnan(r["B"].iloc[2, 0])


def test_block_boot_ratio_brackets_point_estimate():
    rng = np.random.default_rng(1)
    num = rng.normal(0.5, 0.1, 300)
    den = np.ones(300)
    lo, hi = pc.block_boot_ratio(num, den, 500, rng)
    assert lo < num.mean() < hi
