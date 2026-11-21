import json
import numpy as np
import pandas as pd
import pytest
from types import SimpleNamespace

from pit_model_comparison import paired_sharpes, ranked_offers, verify_ledger
import backtest_core as bc
import pit_panel
import pit_model_comparison as comparison


def test_ranked_offers_keep_top_decile_and_break_ties():
    frame = pd.DataFrame({
        "Date": pd.Timestamp("2024-01-02"),
        "isin": [f"id{i:02}" for i in reversed(range(11))],
        "Pred_Prob_1d": 0.50,
        "Pred_Prob_1w": 0.50,
        "Pred_Prob_1m": 0.40,
        "Pred_Prob_6m": 0.30,
    })
    scores = ranked_offers(frame)
    assert set(scores) == {"id00", "id01"}
    assert scores["id00"]["Pred_Prob_1d"].iloc[0] > scores["id01"]["Pred_Prob_1d"].iloc[0]
    assert scores["id00"]["Pred_Prob_1w"].isna().all()


def test_paired_bootstrap_identical_series_has_zero_difference():
    returns = np.linspace(-0.015, 0.016, 60)
    result = paired_sharpes(pd.DataFrame({"lstm": returns, "baseline": returns}))
    assert result["baseline"] == {"difference": 0.0, "ci95": [0.0, 0.0], "adjusted_lower": 0.0}


def test_engine_fills_only_ranked_offers_at_next_open():
    dates = pd.bdate_range("2024-01-02", periods=4)
    stocks = [f"id{i:02}" for i in range(11)]
    offers = ranked_offers(pd.DataFrame({
        "Date": dates[0], "isin": stocks,
        "Pred_Prob_1d": 0.5, "Pred_Prob_1w": 0.4,
        "Pred_Prob_1m": 0.3, "Pred_Prob_6m": 0.2,
    }))
    frames = {
        stock: pd.DataFrame({"Open": [10.0, 11.0, 12.0, 13.0], "Close": 12.0,
                             "Member": True}, index=dates)
        for stock in stocks
    }
    panel = bc.build_panel(pit_panel.attach_scores(frames, offers))
    params = bc.StrategyParams.pit(min_accepted=0.0, std_factor=0.0, impact_k=0.0,
                                   use_spread_cost=False, participation_cap=None)
    result = bc.run_strategy(panel, params)
    assert result.trades.Ticker.tolist() == ["id00", "id01"]
    assert result.trades.BuyDate.tolist() == [dates[1], dates[1]]
    verify_ledger(result, dates, params.initial_value)


def test_common_coverage_accepts_engine_dates_as_list(monkeypatch):
    dates = pd.bdate_range("2024-01-01", periods=130)
    tickers = ["a", "b"]
    engine_panel = SimpleNamespace(
        dates=dates.tolist(), tickers=tickers,
        close=np.full((130, 2), 10.0),
        member=np.ones((130, 2), dtype=bool),
        max_move_to_date=np.zeros((130, 2)),
    )
    monkeypatch.setattr(comparison.prior, "panel_for", lambda *args: engine_panel)
    price = pd.DataFrame({"a": 10.0, "b": 10.0}, index=dates)
    price.loc[dates[3], "b"] = np.nan
    monkeypatch.setattr(comparison.prior, "wide", lambda *args: price)
    matched = pd.DataFrame({"Date": dates[-1], "isin": tickers})
    for arm in comparison.MODELS:
        for column in comparison.PROBS:
            matched[f"{arm}_{column}"] = 0.5
    offers, coverage = comparison.portfolio_inputs(None, matched, bc.StrategyParams.pit())
    assert coverage[2024]["eligible_without_observed_momentum"] == 1
    assert all(set(arm) == {"a"} for arm in offers.values())


def test_coverage_matches_dates_with_different_storage_precision(monkeypatch):
    dates = pd.bdate_range("2016-01-04", periods=61)
    source = pd.DataFrame({"Date": dates.as_unit("us"), "isin": "a", "member": True})
    observed = pd.DataFrame({"Date": dates[-1:].as_unit("ns"), "isin": "a"})
    monkeypatch.setattr(comparison.pit_wf, "file_sha", lambda path: comparison.FROZEN_FILE_HASH)
    monkeypatch.setattr(comparison.pd, "read_parquet", lambda *args, **kwargs: source)
    comparison.verify_forecast_coverage(observed)
    with pytest.raises(ValueError, match="registered development eligibility"):
        comparison.verify_forecast_coverage(observed.assign(isin="different"))


def test_evaluator_writes_four_portfolios_with_synthetic_forecasts(monkeypatch, tmp_path):
    rng = np.random.default_rng(44)
    dates = pd.bdate_range("2016-01-04", periods=440)
    stocks = [f"S{i:02}" for i in range(14)]
    frames, adjusted = {}, {}
    for stock in stocks:
        close = 40 * np.exp(np.cumsum(rng.normal(0.0003, 0.007, len(dates))))
        opening = close * np.exp(rng.normal(0, 0.002, len(dates)))
        frames[stock] = pd.DataFrame({
            "Open": opening, "High": np.maximum(opening, close) * 1.01,
            "Low": np.minimum(opening, close) * 0.99, "Close": close,
            "Volume": 1_000_000.0, "Member": True, "SpreadEst": 0.002,
        }, index=dates)
        adjusted[stock] = pd.DataFrame({"AdjClose": close, "TrClose": close}, index=dates)
    panel = pit_panel.PitData(
        frames, adjusted, pd.DataFrame(columns=["date", "ticker", "factor"]),
        pd.DataFrame(columns=["ex_date", "ticker", "cash"]),
        pd.DataFrame(columns=["date", "ticker", "cash_per_share", "successor_ticker", "successor_shares"]),
        pd.DataFrame({"tr_index": np.linspace(100, 120, len(dates))}, index=dates), dates, dates[-1],
    )
    forecasts = pd.MultiIndex.from_product([dates[126:-126], stocks], names=comparison.KEYS).to_frame(index=False)
    for label in comparison.LABELS:
        forecasts[label] = rng.integers(0, 2, len(forecasts)).astype(float)
    for arm in comparison.MODELS:
        for column in comparison.PROBS:
            forecasts[f"{arm}_{column}"] = rng.uniform(0.05, 0.75, len(forecasts))
    audit = {int(year): {"train_pos_rate": [0.5] * 4} for year in forecasts.Date.dt.year.unique()}
    monkeypatch.setattr(comparison, "FORECAST_ROOT", tmp_path)
    monkeypatch.setattr(comparison, "load_matched_forecasts", lambda: (forecasts, audit))
    monkeypatch.setattr(comparison, "verify_forecast_coverage", lambda matched: None)
    monkeypatch.setattr(comparison.prior.pp, "load_pit", lambda **kwargs: panel)
    comparison.evaluate()
    output = tmp_path / "evaluation"
    result = json.loads((output / "results.json").read_text())
    manifest = json.loads((output / "prescore_manifest.json").read_text())
    assert set(result["portfolios"]) == {"lstm", "logistic", "lightgbm", "momentum"}
    assert set(result["lstm_minus_baselines"]) == {"logistic", "lightgbm", "momentum"}
    assert result["trial_count"] == 45
    assert manifest["registered_trials"] == result["trial_count"]
    assert manifest["fill"] == "next_open"
    assert manifest["confirmation"] == "sealed"
    assert len(list(output.glob("*_trades.csv"))) == 4
    assert len(list(output.glob("*_equity.csv"))) == 4
    with pytest.raises(RuntimeError, match="already exists"):
        comparison.evaluate()
