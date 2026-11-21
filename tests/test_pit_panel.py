"""Tests for pit_panel.py: synthetic conversions, then known securities on the real PIT artifacts
(precondition 2 of research/pit_nextopen_2026-11-20_preregistration.md)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backtest_core as bc  # noqa: E402
import pit_panel as pp  # noqa: E402

T = pd.Timestamp


# ---------------------------------------------------------------- synthetic conversions

def _ca(rows):
    return pd.DataFrame(rows, columns=["isin", "type", "factor", "trading_session", "status"])


def test_split_factor_is_inverse_price_ratio():
    ca = _ca([("X", "Share Split", 0.25, "2020-08-31", "verified")])
    s, d, rep = pp.corporate_action_events(ca, pd.Series(dtype=float))
    assert s.iloc[0]["factor"] == pytest.approx(4.0) and d.empty and rep["split_sessions"] == 1


def test_combined_demerger_and_consolidation_preserve_value():
    # Spin-off (price ratio 0.7) and 1-for-3 consolidation (price ratio 3.0) on the same session, prev close 100.
    ca = _ca([("X", "Demerger", 0.7, "2019-06-03", "verified_combined"),
              ("X", "Share Consolidation", 3.0, "2019-06-03", "verified_combined")])
    pc = pd.Series({("X", T("2019-06-03")): 100.0})
    s, d, _ = pp.corporate_action_events(ca, pc)
    F = s.iloc[0]["factor"]
    cash = d.iloc[0]["cash"]
    assert F == pytest.approx(1 / 3)
    assert cash == pytest.approx(100 * 0.3 * 3)          # $30 per old share = $90 per new share
    # holder of 3 old shares: 1 new share at 100*0.7*3 = 210 plus 90 cash = 300 = 3 x 100
    new_price = 100 * 0.7 * 3.0
    assert 3 * F * new_price + 3 * F * cash == pytest.approx(300.0)


def test_no_price_effect_pair_and_unverified_are_skipped():
    ca = _ca([("X", "Share Consolidation", 100.0, "2011-03-21", "no_price_effect_combined"),
              ("X", "Share Split", 0.01, "2011-03-21", "no_price_effect_combined"),
              ("Y", "Demerger", 0.8, None, "unverified"),
              ("Z", "Demerger", 0.8, "2012-01-03", "outside_window_or_no_prices")])
    s, d, rep = pp.corporate_action_events(ca, pd.Series(dtype=float))
    assert s.empty and d.empty
    assert rep["events_unused"] == 2


def _sm():
    return pd.DataFrame({"isin": ["SUCC", "OTHER"], "ric": ["S.N", "O.N"],
                         "valid_from": [T("2011-01-03")] * 2, "valid_to": [T("2099-12-31")] * 2,
                         "role": ["primary"] * 2})


def _st(**kw):
    base = dict(isin="TGT", last_bar="2021-01-15", cash_per_share=np.nan, successor_shares_per_share=np.nan,
                successor_ric=np.nan, successor_open_date=np.nan, successor_open=np.nan,
                settlement_value_used=np.nan, outcome="x")
    base.update(kw)
    return pd.DataFrame([base])


SESS = pd.DatetimeIndex(pd.to_datetime(["2021-01-14", "2021-01-15", "2021-01-19", "2021-01-20"]))


def test_settlement_date_is_next_session_and_cash_uses_documented_value():
    df, _ = pp.settlement_events(_st(cash_per_share=40.0, settlement_value_used=40.0), _sm(), SESS, {"TGT"})
    r = df.iloc[0]
    assert r["date"] == T("2021-01-19") and r["cash_per_share"] == 40.0 and r["leg"] == "cash"


def test_stock_leg_kept_when_successor_in_panel_and_extra_added():
    st = _st(cash_per_share=10.0, successor_shares_per_share=0.5, successor_ric="S.N",
             successor_open_date="2021-01-19", successor_open=60.0, settlement_value_used=43.0)   # 3 = CVR
    df, rep = pp.settlement_events(st, _sm(), SESS, {"TGT", "SUCC"})
    r = df.iloc[0]
    assert r["leg"] == "stock" and r["successor_ticker"] == "SUCC" and r["successor_shares"] == 0.5
    assert r["cash_per_share"] == pytest.approx(13.0) and rep["extra_added_to_cash"] == 1


def test_successor_outside_panel_converts_to_cash():
    st = _st(cash_per_share=60.0, successor_shares_per_share=2.1243, successor_ric="AZN.N",
             settlement_value_used=182.5)
    df, rep = pp.settlement_events(st, _sm(), SESS, {"TGT", "SUCC"})
    assert df.iloc[0]["leg"] == "cash" and df.iloc[0]["cash_per_share"] == 182.5
    assert rep["stock_converted_to_cash"] == 1


def test_settlement_after_panel_end_dropped():
    df, _ = pp.settlement_events(_st(last_bar="2021-01-20", settlement_value_used=1.0), _sm(), SESS, {"TGT"})
    assert df.empty


# ---------------------------------------------------------------- known securities on the real artifacts

AAPL, MMI, CXO, COP, MRO, NBR = ("US0378331005", "US6200971058", "US20605P1012", "US20825C1045",
                                 "US5658491064", "BMG6359F1370")
HAVE = (pp.PIT_DIR / "prices_pit.parquet").exists()
real = pytest.mark.skipif(not HAVE, reason="PIT artifacts not built")

P0 = dict(min_accepted=0.25, std_factor=0.0, max_positions=1, cost_bps=0.0, min_price=0.0, spike_threshold=1e9,
          fill="next_open", use_spread_cost=False, participation_cap=None)


@pytest.fixture(scope="module")
def pit():
    return pp.load_pit(end="2024-12-31", isins=[AAPL, MMI, CXO, COP, MRO, NBR], strict=False)


SVB = "US78486Q1013"      # failed bank: no consolidated series; venue_scaled volume, no quotes (amendment 4)


def test_lacking_securities_rule():
    def rows(isin, vol, src, q, member=True):
        return [{"isin": isin, "member": member, "volume_adv": vol, "volume_source": src, "quoted_spread": q}] * 3
    px = pd.DataFrame(rows("OK", 1e6, "consolidated", 0.001) + rows("SCALED", 1e5, "venue_scaled", np.nan)
                      + rows("NOVOL", np.nan, "none", 0.001) + rows("NOQ", 1e6, "consolidated", np.nan)
                      + rows("NEVER", np.nan, "none", np.nan, member=False))
    assert pp.lacking_securities(px) == ["NOQ", "NOVOL"]


@real
def test_strict_accepts_documented_fallback_and_uses_volume_adv():
    with pytest.raises(bc.ConfirmationPeriodError):
        pp.load_pit(end="2025-06-30", isins=[AAPL])                      # guard still applies
    ok = pp.load_pit(end="2024-12-31", isins=[AAPL, SVB])                # strict: SVB is on the venue_scaled fallback
    assert ok.report["member_securities_without_volume_or_quotes"] == []
    assert ok.report["member_sessions_volume_source"].get("venue_scaled", 0) > 0
    f = ok.frames[SVB]
    assert f.loc[f["Member"], "Volume"].notna().mean() > 0.99
    assert ok.report["member_sessions_spread_source"].get("estimator", 0) > 0


@real
def test_spread_uses_trailing_quoted_median(pit):
    s = pit.frames[AAPL]["SpreadEst"]
    assert s.loc["2016":].notna().all()
    assert s.loc["2016":].median() < 0.0005                # quoted S&P spreads are a few bp, not ~27 bp
    src = pit.report["member_sessions_spread_source"]
    assert src.get("quoted", 0) > 0


def _run(pit, isin, signal_date, horizon="1m", **kw):
    f = pit.frames[isin]
    s = pd.DataFrame(index=f.index)
    for h in bc.PERIODS:
        s[f"Pred_Prob_{h}"] = np.where((f.index == T(signal_date)) & (h == horizon), 0.9, 0.0)
        s[f"Pred_Prob_Std_{h}"] = 0.0
    panel = pp.build_pit_panel(pit, {isin: s})
    return panel, bc.run_strategy(panel, bc.StrategyParams(**{**P0, **kw}))


def _idx(panel, d):
    return panel.dates.index(T(d))


@real
def test_guard_blocks_reserved_period():
    with pytest.raises(bc.ConfirmationPeriodError):
        pp.load_pit(end="2025-06-30", isins=[AAPL])


@real
def test_real_frames_are_raw_with_consolidated_volume(pit):
    f = pit.frames[AAPL]
    assert f.loc["2020-08-28", "Close"] == pytest.approx(499.23) and f.loc["2020-08-31", "Close"] == pytest.approx(129.04)
    assert f["Volume"].notna().mean() > 0.99 and f["SpreadEst"].notna().mean() > 0.95
    assert pit.frames[AAPL].index.max() <= T("2024-12-31")
    a = pit.adjusted[AAPL]
    assert a.loc["2020-08-31", "AdjClose"] / a.loc["2020-08-28", "AdjClose"] == pytest.approx(129.04 / 499.23 * 4)


@real
def test_real_split_preserves_value(pit):
    assert ((pit.splits["ticker"] == AAPL) & (pit.splits["date"] == T("2020-08-31"))).any()
    panel, res = _run(pit, AAPL, "2020-08-20")
    i = _idx(panel, "2020-08-31")
    assert res.equity[i] / res.equity[i - 1] == pytest.approx(4 * 129.04 / 499.23, rel=1e-9)


@real
def test_real_cash_dividend_credited(pit):
    panel, res = _run(pit, AAPL, "2014-07-31")
    tr = res.trades.iloc[0]
    shares = 5000 / tr["EntryPrice"]
    assert res.dividends == pytest.approx(shares * 0.47, rel=1e-9)


@real
def test_real_spin_off_credits_value_removed(pit):
    d = pit.dividends[(pit.dividends["ticker"] == MRO) & (pit.dividends["kind"] == "distribution_in_kind")]
    row = d[d["ex_date"] == T("2011-07-01")].iloc[0]
    pc = pit.frames[MRO]["Close"].loc[:"2011-06-30"].dropna().iloc[-1]
    assert row["cash"] == pytest.approx(pc * (1 - 0.607062), rel=1e-4)
    panel, res = _run(pit, MRO, "2011-06-20")
    i = _idx(panel, "2011-07-01")
    p1 = pit.frames[MRO]["Close"].loc["2011-07-01"]
    assert res.equity[i] / res.equity[i - 1] == pytest.approx((p1 + row["cash"]) / pc, rel=1e-6)
    # same day economically: within 5% of the total-return-adjusted move
    a = pit.adjusted[MRO]["TrClose"]
    assert res.equity[i] / res.equity[i - 1] == pytest.approx(a.loc["2011-07-01"] / a.loc["2011-06-30"], rel=0.05)


@real
def test_real_second_spin_off_present(pit):
    d = pit.dividends[(pit.dividends["ticker"] == COP) & (pit.dividends["kind"] == "distribution_in_kind")]
    assert (d["ex_date"] == T("2012-05-01")).any()


@real
def test_real_cash_merger_settles_at_deal_price(pit):
    panel, res = _run(pit, MMI, "2012-05-10")
    tr = res.trades.iloc[0]
    assert tr["ExitType"] == "settlement" and tr["ExitPrice"] == pytest.approx(40.0)
    assert tr["SellDate"] == T("2012-05-22")


@real
def test_real_stock_merger_settles_at_successor_open(pit):
    st = pit.settlements[pit.settlements["ticker"] == CXO].iloc[0]
    assert st["leg"] == "stock" and st["successor_ticker"] == COP and st["successor_shares"] == pytest.approx(1.46)
    panel, res = _run(pit, CXO, "2021-01-05")
    tr = res.trades.iloc[0]
    cop_open = pit.frames[COP].loc["2021-01-19", "Open"]
    assert tr["ExitType"] == "settlement" and tr["SellDate"] == T("2021-01-19")
    assert tr["ExitPrice"] == pytest.approx(1.46 * cop_open, rel=1e-9)


@real
def test_real_index_deletion_blocks_entry_but_not_holding(pit):
    f = pit.frames[NBR]
    assert bool(f.loc["2015-03-20", "Member"]) and not bool(f.loc["2015-03-23", "Member"])
    after = _run(pit, NBR, "2015-03-25", use_member_mask=True)[1]
    assert len(after.trades) == 0
    before = _run(pit, NBR, "2015-03-10", use_member_mask=True)[1]
    tr = before.trades.iloc[0]
    assert tr["ExitType"] == "time" and tr["SellDate"] > T("2015-03-23")     # held through the deletion
