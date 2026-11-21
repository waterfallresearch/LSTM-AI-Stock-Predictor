import numpy as np
import pandas as pd
import pytest

import backtest_core as bc
from pit_breadth import paired_compare, targets_for, run_portfolio
from pit_price_ranks import schedules, signals


def make_panel(opens, *, dates=None, splits=None):
    dates = dates if dates is not None else pd.bdate_range("2020-01-02", periods=len(next(iter(opens.values()))))
    frames = {}
    for name, prices in opens.items():
        close = pd.Series(prices, index=dates).ffill()
        frames[name] = pd.DataFrame({"Open": prices, "Close": close, "Member": True})
        for h in bc.PERIODS:
            frames[name][f"Pred_Prob_{h}"] = np.nan
            frames[name][f"Pred_Prob_Std_{h}"] = 0.0
    return bc.build_panel(frames, splits=splits)


def params(**overrides):
    return bc.StrategyParams.pit(**dict({
        "initial_value": 1000, "participation_cap": None, "impact_k": 0, "use_spread_cost": False,
    }, **overrides))


def test_missing_open_cancels_buy_and_defers_exit_without_terminal_sale():
    panel = make_panel({"A": [10, 10, 10, np.nan, 12, 13], "B": [20, np.nan, 20, 20, 20, 20]})
    a, b = [panel.tickers.index(t) for t in "AB"]
    result, _ = run_portfolio(panel, params(), {0: {a: 0.5, b: 0.5}, 2: {b: 1.0}})
    assert result.cancelled_entries == result.deferred_exits == 1
    assert result.trades.SellDate.tolist() == [panel.dates[4]]
    assert result.equity[-1] == pytest.approx(1100)
    assert result.open_at_end == 1


def test_trim_and_split_scale_deferred_sale():
    dates = pd.bdate_range("2020-01-02", periods=7)
    splits = pd.DataFrame({"date": [dates[4]], "ticker": ["A"], "factor": [2.0]})
    panel = make_panel({"A": [10, 10, 10, np.nan, 5, 5, 5]}, dates=dates, splits=splits)
    result, _ = run_portfolio(panel, params(), {0: {0: 1.0}, 2: {0: 0.5}})
    sold = [cash for cash in result.cash_events if cash["kind"] == "sell"]
    assert sold[0]["shares"] == pytest.approx(100)
    assert result.cash_path[-1] == pytest.approx(500)
    assert result.holdings_path[-1] == pytest.approx(500)


def test_split_day_adv_and_costs_use_actual_share_units():
    dates = pd.bdate_range("2020-01-02", periods=6)
    panel = make_panel(
        {"A": [10, 10, 10, 5, 5, 5]}, dates=dates,
        splits=pd.DataFrame({"date": [dates[3]], "ticker": ["A"], "factor": [2.0]}),
    )
    panel.adv20 = np.array([[2000], [2000], [1000], [2000], [2000], [2000]], dtype=float)
    panel.spread_est = np.full((6, 1), 0.002)
    result, _ = run_portfolio(
        panel, params(participation_cap=0.05, cost_bps=1, use_spread_cost=True), {0: {0: 1.0}, 2: {}},
    )
    sales = [event for event in result.cash_events if event["kind"] == "sell"]
    assert len(sales) == 2
    assert sales[0]["shares"] == pytest.approx(100)
    assert sales[0]["cost"] == pytest.approx(0.55)
    assert result.equity[-1] == pytest.approx(1000 - result.total_costs)


def test_observed_endpoints_and_identifier_ties():
    dates = pd.bdate_range("2020-01-02", periods=160)
    panel = make_panel({s: [20.0] * len(dates) for s in "CBADEF"}, dates=dates)
    tr = pd.DataFrame(20.0, index=dates, columns=panel.tickers)
    month_end = max(i for i in range(126, len(dates) - 1) if dates[i].month != dates[i + 1].month)
    tr.loc[dates[month_end - 126], "A"] = np.nan
    targets, _ = targets_for(panel, tr, params())
    assert [panel.tickers[j] for j in targets["five"][month_end]] == list("BCDEF")
    assert [panel.tickers[j] for j in targets["broad"][month_end]] == ["B"]


def test_identical_branches_have_zero_paired_difference():
    values = np.random.default_rng(31).normal(0, 0.01, 100)
    assert paired_compare(values, values) == {
        "difference": 0, "lower_one_sided_95": 0, "ci95": [0, 0],
    }


def test_confirmation_guard_checks_target_rebalance():
    panel = make_panel({"A": [10, 11]})
    panel.dates = pd.bdate_range("2025-01-02", periods=2).tolist()
    with pytest.raises(bc.ConfirmationPeriodError):
        bc.run_strategy(panel, params(), targets={0: {0: 1.0}})


def test_price_feature_snapshots_do_not_read_signal_day_or_forward():
    dates = pd.bdate_range("2018-01-02", periods=260)
    values = pd.DataFrame({"A": np.arange(10., 270.)}, index=dates)
    control, features = signals(values, values, values)
    changed = values.copy()
    changed.iloc[-1] *= 100
    new_control, new_features = signals(changed, changed, changed)
    pd.testing.assert_frame_equal(control, new_control)
    for a, b in zip(features, new_features):
        pd.testing.assert_frame_equal(a, b)


def test_price_composite_has_common_mask_and_stable_tie_breaks():
    dates = pd.to_datetime(["2024-01-30", "2024-01-31", "2024-02-01"])
    panel = make_panel({stock: [10.0] * 3 for stock in "ABCDEF"}, dates=dates)
    base = pd.DataFrame(1.0, index=dates, columns=panel.tickers)
    factor = base.copy()
    factor.loc[dates[1], "A"] = np.nan
    factor.loc[dates[1], "F"] = 9.0
    targets, _, counts = schedules(panel, base, (factor, base, base, base), params())
    assert counts == [5]
    assert list(targets["momentum"][1]) == [1, 2, 3, 4, 5]
    assert list(targets["composite"][1]) == [5, 1, 2, 3, 4]
