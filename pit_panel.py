"""Adapter: point-in-time S&P 500 artifacts -> backtest_core.build_panel inputs.

Implements the "Data (frozen)" section of research/pit_nextopen_2026-11-20_preregistration.md.

    pit = load_pit(end="2024-12-31")             # raises for dates >= 2025-01-02 unless confirm=True
    panel = build_pit_panel(pit, scores)          # scores: {isin: DataFrame of Pred_Prob_* / Pred_Prob_Std_*}

Conventions (all verified on the data, see tests/test_pit_panel.py)
- Execution prices are RAW (unadjusted) bars from prices_pit.parquet; bars with valid_bar=False become NaN.
- Volume is consolidated_pit.parquet `volume_adv`: consolidated volume where it exists, else venue volume scaled by
  the trailing 63-session median consolidated/venue ratio of other securities on the same venue (causal;
  `volume_source` = consolidated | venue_scaled | none). Never raw venue volume (acceptance amendment P2;
  amendment 4 of the preregistration).
- SpreadEst is the trailing 21-session median (>= 10 observations) of the consolidated closing quoted spread
  (consolidated_pit.parquet quoted_spread, fractional, dated at the close it was observed). Where that is missing,
  the daily-bar estimator spreads_pit.parquet spread_est is used (it overstates S&P 500 spreads about 10x, so it is
  conservative), then the engine's fallback. Amendment 1 of the preregistration.
- strict=True (default) refuses to load when any security that is ever a member has no volume at all
  (volume_source never consolidated/venue_scaled), or has no quoted spread at all without being on the documented
  venue_scaled fallback (those use spread_est). Such securities could never be entered under the ADV participation
  cap, which would silently shrink the universe. Tests pass strict=False. See `lacking_securities`.
- LSEG factors are price ratios: adjusted = raw * factor, cumulative backward from the latest session; an event's
  `factor` is the post/pre price ratio (a 2-for-1 split has factor 0.5).
- Share-count events (split, consolidation, conversion, "Added (missing from LSEG)") -> engine split with
  factor = 1 / prod(price ratios) on the trading session.
- Distributions in kind (demerger, rights issue) -> engine cash dividend on the trading session worth
  close(t-1) * (1 - prod(distribution ratios)) per pre-event share, restated per post-split share when a share-count
  event falls on the same session. This preserves the holder's value exactly as the adjusted series does.
- Cash dividends: dividends_pit.csv amounts (raw, per share on the ex-date).
- Settlements: settlement date = first session after `last_bar`. A stock leg is kept only if the successor (dated
  RIC -> ISIN via security_master.csv) is in the panel. Otherwise, and for cash-only deals, the documented
  `settlement_value_used` is paid in cash. If the documented value differs from cash + shares x successor open by
  more than 0.5% (CVRs, special dividends), the difference is added to the cash leg.
- Adjusted series (for features) use the backward factors. Their LEVELS embed later splits, so only scale-invariant
  features (returns, ratios, z-scores) may use them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

import backtest_core as bc

ROOT = Path(__file__).resolve().parent
PIT_DIR = ROOT / "TrainingData" / "indicators_data" / "pit"
RESEARCH_END = "2024-12-31"

SHARE_TYPES = {"Share Split", "Share Consolidation", "Share Conversion", "Added (missing from LSEG)"}
DIST_TYPES = {"Demerger", "Rights Issue"}
OK_STATUS = ("verified", "added_reviewed", "no_price_effect_combined")   # prefixes
EXTRA_TOL = 0.005
SPREAD_WINDOW = 21
SPREAD_MIN_OBS = 10


class IncompleteDataError(ValueError):
    """Raised by load_pit(strict=True) when member securities lack volume, or quotes without the documented fallback."""


def lacking_securities(px: pd.DataFrame) -> list[str]:
    """Ever-member securities with no usable volume, or no quotes and no venue_scaled (documented) fallback.
    px columns: isin, member, volume_adv, volume_source, quoted_spread."""
    g = px.groupby("isin")
    ever_member = g["member"].any()
    no_vol = g["volume_adv"].apply(lambda s: s.notna().sum() == 0)
    no_q = g["quoted_spread"].apply(lambda s: s.notna().sum() == 0)
    scaled = g["volume_source"].apply(lambda s: (s == "venue_scaled").any())
    return sorted(set(ever_member[ever_member & (no_vol | (no_q & ~scaled))].index))


@dataclass
class PitData:
    frames: dict[str, pd.DataFrame]          # isin -> Open High Low Close Volume Member SpreadEst (raw)
    adjusted: dict[str, pd.DataFrame]        # isin -> AdjOpen AdjHigh AdjLow AdjClose TrClose AdjVolume
    splits: pd.DataFrame                     # date, ticker, factor
    dividends: pd.DataFrame                  # ex_date, ticker, cash, kind
    settlements: pd.DataFrame                # date, ticker, cash_per_share, successor_ticker, successor_shares, ...
    spy: pd.DataFrame                        # session-indexed open, close, dividend, tr_index
    sessions: pd.DatetimeIndex
    end: pd.Timestamp
    report: dict = field(default_factory=dict)


def _ok(status: pd.Series) -> pd.Series:
    return status.astype(str).str.startswith(OK_STATUS)


def corporate_action_events(ca: pd.DataFrame, prev_close: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """ca: corporate_actions_pit rows (isin, type, factor, trading_session, status).
    prev_close: raw close of the session before each (isin, trading_session), indexed by (isin, session).
    Returns (splits, distributions, report)."""
    use = ca[_ok(ca["status"]) & ca["trading_session"].notna() & np.isfinite(ca["factor"]) & (ca["factor"] > 0)].copy()
    unused = ca.drop(use.index)
    use["kind"] = np.where(use["type"].isin(SHARE_TYPES), "share", np.where(use["type"].isin(DIST_TYPES), "dist", "other"))
    other = use[use["kind"] == "other"]
    rows_s, rows_d = [], []
    for (isin, sess), g in use[use["kind"] != "other"].groupby(["isin", "trading_session"]):
        share_ratio = float(g.loc[g["kind"] == "share", "factor"].prod())     # price ratio from share-count events
        dist_ratio = float(g.loc[g["kind"] == "dist", "factor"].prod())
        F = 1.0 / share_ratio                                                   # new shares per old share
        if abs(F - 1.0) > 1e-9:
            rows_s.append({"date": pd.Timestamp(sess), "ticker": isin, "factor": F})
        if dist_ratio < 1.0 - 1e-9:
            pc = prev_close.get((isin, pd.Timestamp(sess)), np.nan)
            if not np.isfinite(pc):
                continue
            rows_d.append({"ex_date": pd.Timestamp(sess), "ticker": isin, "cash": pc * (1.0 - dist_ratio) / F,
                           "kind": "distribution_in_kind"})
    report = {"events_used": int(len(use) - len(other)), "events_unused": int(len(unused)),
              "events_other_type": int(len(other)),
              "unused_by_status": unused["status"].value_counts().to_dict(),
              "split_sessions": len(rows_s), "distribution_sessions": len(rows_d)}
    return (pd.DataFrame(rows_s, columns=["date", "ticker", "factor"]),
            pd.DataFrame(rows_d, columns=["ex_date", "ticker", "cash", "kind"]), report)


def successor_isin(sm: pd.DataFrame, ric, when: pd.Timestamp) -> str | None:
    if not isinstance(ric, str) or not ric:
        return None
    m = sm[(sm["ric"] == ric) & (sm["valid_from"] <= when) & (sm["valid_to"] > when)]
    if m.empty:
        return None
    prim = m[m["role"] == "primary"]
    return str((prim if len(prim) else m)["isin"].iloc[0])


def settlement_events(st: pd.DataFrame, sm: pd.DataFrame, sessions: pd.DatetimeIndex,
                      in_panel: set[str]) -> tuple[pd.DataFrame, dict]:
    rows, conv, extra_n = [], 0, 0
    for r in st.itertuples(index=False):
        if r.isin not in in_panel or pd.isna(r.last_bar):
            continue
        k = sessions.searchsorted(pd.Timestamp(r.last_bar), side="right")
        if k >= len(sessions):
            continue                                   # pay date after the panel end
        date = sessions[k]
        cash = float(r.cash_per_share) if pd.notna(r.cash_per_share) else 0.0
        ss = float(r.successor_shares_per_share) if pd.notna(r.successor_shares_per_share) else 0.0
        used = float(r.settlement_value_used) if pd.notna(r.settlement_value_used) else np.nan
        when = pd.Timestamp(r.successor_open_date) if pd.notna(r.successor_open_date) else date
        succ = successor_isin(sm, r.successor_ric, when) if ss > 0 else None
        if ss > 0 and succ is not None and succ in in_panel and succ != r.isin:
            so = float(r.successor_open) if pd.notna(r.successor_open) else np.nan
            if np.isfinite(used) and np.isfinite(so):
                extra = used - (cash + ss * so)
                if abs(extra) > EXTRA_TOL * max(abs(used), 1e-9):
                    cash += extra
                    extra_n += 1
            rows.append({"date": date, "ticker": r.isin, "cash_per_share": cash, "successor_ticker": succ,
                         "successor_shares": ss, "outcome": r.outcome, "leg": "stock"})
        else:
            if ss > 0:
                conv += 1
            value = used if np.isfinite(used) else cash
            rows.append({"date": date, "ticker": r.isin, "cash_per_share": value, "successor_ticker": None,
                         "successor_shares": 0.0, "outcome": r.outcome, "leg": "cash"})
    df = pd.DataFrame(rows, columns=["date", "ticker", "cash_per_share", "successor_ticker", "successor_shares",
                                     "outcome", "leg"])
    return df, {"settlements": len(df), "stock_legs": int((df["leg"] == "stock").sum()),
                "stock_converted_to_cash": conv, "extra_added_to_cash": extra_n}


def load_pit(start: str | None = None, end: str | None = RESEARCH_END, *, isins: list[str] | None = None,
             confirm: bool = False, strict: bool = True, pit_dir: Path = PIT_DIR) -> PitData:
    """Load the PIT artifacts up to `end` (inclusive). `start` only trims the returned frames; history before it
    is still used for prev-close lookups. `isins` restricts the universe (for tests)."""
    d = Path(pit_dir)
    px = pd.read_parquet(d / "prices_pit.parquet")
    px["session"] = pd.to_datetime(px["session"])
    end_ts = pd.Timestamp(end) if end is not None else px["session"].max()
    bc.guard_confirmation([end_ts], confirm, "load_pit")
    px = px[px["session"] <= end_ts]
    sessions = pd.DatetimeIndex(sorted(px["session"].unique()))
    if isins is not None:
        px = px[px["isin"].isin(isins)]
    keep = set(px["isin"].unique())

    def side(name: str, cols: list[str]) -> pd.DataFrame:
        t = pd.read_parquet(d / name, columns=["session", "isin"] + cols)
        t["session"] = pd.to_datetime(t["session"])
        return t[(t["session"] <= end_ts) & t["isin"].isin(keep)]

    px = (px.merge(side("consolidated_pit.parquet", ["volume_adv", "volume_source", "quoted_spread"]), on=["session", "isin"],
                   how="left")
            .merge(side("spreads_pit.parquet", ["spread_est"]), on=["session", "isin"], how="left")
            .merge(side("adjustment_factors_pit.parquet", ["split_factor", "tr_factor"]), on=["session", "isin"],
                   how="left"))
    for c in ["open", "high", "low", "close"]:
        px.loc[~px["valid_bar"], c] = np.nan
    px = px.sort_values(["isin", "session"])

    px["volume_source"] = px["volume_source"].fillna("none")
    lacking = lacking_securities(px)
    if strict and lacking:
        raise IncompleteDataError(
            f"{len(lacking)} member securities have no volume, or no quotes without the venue_scaled fallback "
            f"(e.g. {lacking[:5]}). "
            "Fix the consolidated mapping in the data layer, or pass strict=False for diagnostics only.")

    q = px["quoted_spread"].where(px["quoted_spread"] > 0)
    qmed = q.groupby(px["isin"]).transform(
        lambda s: s.rolling(SPREAD_WINDOW, min_periods=SPREAD_MIN_OBS).median())
    px["spread_used"] = qmed.where(qmed.notna(), px["spread_est"])
    spread_src = np.where(qmed.notna(), "quoted", np.where(px["spread_est"].notna(), "estimator", "missing"))
    px["prev_close"] = px.groupby("isin")["close"].transform(lambda s: s.ffill().shift(1))
    prev_close = px.set_index(["isin", "session"])["prev_close"]

    frames, adjusted = {}, {}
    for isin, g in px.groupby("isin", sort=True):
        g = g.set_index("session")
        g.index.name = "Date"
        frames[isin] = pd.DataFrame({"Open": g["open"], "High": g["high"], "Low": g["low"], "Close": g["close"],
                                     "Volume": g["volume_adv"], "Member": g["member"].astype(bool),
                                     "SpreadEst": g["spread_used"]})
        sf, tf = g["split_factor"], g["tr_factor"]
        adjusted[isin] = pd.DataFrame({"AdjOpen": g["open"] * sf, "AdjHigh": g["high"] * sf, "AdjLow": g["low"] * sf,
                                       "AdjClose": g["close"] * sf, "TrClose": g["close"] * tf,
                                       "AdjVolume": g["volume_adv"] / sf})

    ca = pd.read_csv(d / "corporate_actions_pit.csv")
    ca = ca[ca["isin"].isin(keep)]
    ca = ca[pd.to_datetime(ca["trading_session"]).le(end_ts) | ca["trading_session"].isna()]
    splits, dists, ca_rep = corporate_action_events(ca, prev_close)

    dv = pd.read_csv(d / "dividends_pit.csv", parse_dates=["ex_date"])
    dv = dv[dv["isin"].isin(keep) & (dv["ex_date"] <= end_ts) & np.isfinite(dv["amount"]) & (dv["amount"] > 0)]
    cash_div = pd.DataFrame({"ex_date": dv["ex_date"], "ticker": dv["isin"], "cash": dv["amount"].astype(float),
                             "kind": dv["type"].astype(str)})
    dividends = pd.concat([cash_div, dists], ignore_index=True)

    sm = pd.read_csv(d / "security_master.csv", parse_dates=["valid_from", "valid_to"])
    st = pd.read_csv(d / "settlement_pit.csv")
    settlements, st_rep = settlement_events(st, sm, sessions, keep)

    spy = pd.read_csv(d / "spy_pit.csv", parse_dates=["session"]).set_index("session")
    spy = spy[spy.index <= end_ts]

    if start is not None:
        s0 = pd.Timestamp(start)
        frames = {k: v[v.index >= s0] for k, v in frames.items()}
        adjusted = {k: v[v.index >= s0] for k, v in adjusted.items()}

    member_rows = int(px["member"].sum())
    report = {"end": str(end_ts.date()), "securities": len(frames), "sessions": len(sessions),
              "member_sessions": member_rows,
              "member_sessions_missing_volume": int((px["member"] & px["volume_adv"].isna()).sum()),
              "member_sessions_volume_source": px.loc[px["member"], "volume_source"].value_counts().to_dict(),
              "member_sessions_spread_source": pd.Series(spread_src[px["member"].to_numpy()]).value_counts().to_dict(),
              "member_securities_without_volume_or_quotes": lacking,
              "member_sessions_invalid_bar": int((px["member"] & ~px["valid_bar"]).sum()),
              "corporate_actions": ca_rep, "cash_dividends": int(len(cash_div)),
              "cash_dividends_by_type": cash_div["kind"].value_counts().to_dict(), "settlement": st_rep}
    return PitData(frames, adjusted, splits, dividends, settlements, spy, sessions, end_ts, report)


def attach_scores(frames: dict[str, pd.DataFrame], scores: dict[str, pd.DataFrame] | None) -> dict[str, pd.DataFrame]:
    """Add Pred_Prob_* / Pred_Prob_Std_* columns (NaN where no score, so no signal)."""
    cols = [f"Pred_Prob_{h}" for h in bc.PERIODS] + [f"Pred_Prob_Std_{h}" for h in bc.PERIODS]
    out = {}
    for isin, f in frames.items():
        f = f.copy()
        s = scores.get(isin) if scores else None
        for c in cols:
            f[c] = s[c].reindex(f.index) if s is not None and c in s else np.nan
        out[isin] = f
    return out


def build_pit_panel(pit: PitData, scores: dict[str, pd.DataFrame] | None = None, start=None, *,
                    confirm: bool = False) -> bc.Panel:
    return bc.build_panel(attach_scores(pit.frames, scores), start=start, end=pit.end,
                          splits=pit.splits, dividends=pit.dividends[["ex_date", "ticker", "cash"]],
                          settlements=pit.settlements[["date", "ticker", "cash_per_share", "successor_ticker",
                                                       "successor_shares"]],
                          confirm=confirm)
