"""Pre-close (3:40 PM) execution test with a reversal proxy (research/preclose_2026-11-20_preregistration.md).

Variants (one-session holds, bottom decile of the day-t move, equal weight, excess vs the eligible universe):
  A  signal close t,  entry close t,    exit close t+1   (look-ahead reference)
  D  signal 3:40 t,   entry close t,    exit close t+1   (market-on-close; the candidate)
  B  signal close t,  entry open t+1,   exit open t+2
  C  signal close t,  entry close t+1,  exit close t+2

Usage:  python preclose_proxy.py [--bars DIR] [--boot 5000]
Uses the reserved period (user-approved 2026-11-20) through pit_panel.load_pit(confirm=True).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import backtest_core as bc

ROOT = Path(__file__).resolve().parent
BARS = ROOT / "TrainingData" / "indicators_data" / "lseg" / "intraday" / "5min_20261120"
OUT = ROOT / "research"
TAG = "preclose_2026-11-20"
WINDOW = ("2025-11-19", "2026-11-18")
SNAP_NY = "15:35"          # bar label (interval start) covering 15:35-15:40 New York time
EARLIEST_FALLBACK_NY = "15:00"
SEED = 20261120
DECILE = 0.10


# ----------------------------------------------------------------------------- snapshot

def snapshot_from_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """bars: naive-UTC-indexed 5-minute bars with TRDPRC_1 (and optionally BID/ASK).
    Returns one row per New York session date: price (last trade in the 15:35 bar, else the last trade in bars
    labelled 15:00-15:35), bid, ask, and the label actually used."""
    if bars.empty:
        return pd.DataFrame(columns=["price", "bid", "ask", "label"])
    idx = pd.DatetimeIndex(bars.index).tz_localize("UTC").tz_convert("America/New_York")
    b = bars.copy()
    b.index = idx
    b = b[(b.index.strftime("%H:%M") >= EARLIEST_FALLBACK_NY) & (b.index.strftime("%H:%M") <= SNAP_NY)]
    b = b[pd.to_numeric(b["TRDPRC_1"], errors="coerce").notna()]
    if b.empty:
        return pd.DataFrame(columns=["price", "bid", "ask", "label"])
    last = b.groupby(b.index.date).tail(1)

    def col(name: str) -> np.ndarray:
        if name not in last:
            return np.full(len(last), np.nan)
        return pd.to_numeric(last[name], errors="coerce").to_numpy(dtype=float)

    out = pd.DataFrame({"price": col("TRDPRC_1"), "bid": col("BID"), "ask": col("ASK"),
                        "label": last.index.strftime("%H:%M")},
                       index=pd.DatetimeIndex(pd.to_datetime(last.index.date), name="Date"))
    return out


# ----------------------------------------------------------------------------- returns

def wide(frames: dict[str, pd.DataFrame], col: str, dates: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({k: v[col].reindex(dates) for k, v in frames.items()})


def basket_excess(signal: pd.DataFrame, ret: pd.DataFrame, elig: pd.DataFrame, cost: pd.DataFrame | None = None,
                  q: float = DECILE, bottom: bool = True) -> pd.DataFrame:
    """Per date: equal-weight return of the bottom (or top) q of `signal` among eligible names with a finite
    signal and return, minus the eligible universe's equal-weight return. cost (same shape) is subtracted per name."""
    rows = []
    for d in signal.index:
        ok = elig.loc[d] & signal.loc[d].notna() & ret.loc[d].notna()
        n = int(ok.sum())
        if n < 20:
            continue
        s = signal.loc[d][ok]
        k = max(int(round(q * n)), 1)
        pick = s.nsmallest(k).index if bottom else s.nlargest(k).index
        r = ret.loc[d][ok]
        uni = float(r.mean())
        gross = float(r[pick].mean()) - uni
        c = float(cost.loc[d][pick].mean()) if cost is not None else 0.0
        rows.append({"Date": d, "n": n, "k": k, "gross": gross, "net": gross - c, "names": list(pick)})
    return pd.DataFrame(rows).set_index("Date") if rows else pd.DataFrame(columns=["n", "k", "gross", "net", "names"])


def nw_stat(x: pd.Series, lags: int = 5) -> dict:
    x = x.dropna()
    return {"n": int(len(x)), "mean": float(x.mean()) if len(x) else float("nan"),
            "nw_t": bc.newey_west_t(x.to_numpy(), lags=lags) if len(x) > lags + 2 else float("nan"),
            "sharpe": float(np.sqrt(252) * x.mean() / x.std(ddof=1)) if len(x) > 2 and x.std(ddof=1) > 0 else float("nan")}


def block_boot_ratio(num: np.ndarray, den: np.ndarray, n_boot: int, rng: np.random.Generator, block: int = 20) -> list:
    n = len(num)
    nb = int(np.ceil(n / block))
    starts = rng.integers(0, n - block + 1, size=(n_boot, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_boot, -1)[:, :n]
    r = num[idx].mean(1) / den[idx].mean(1)
    return np.nanpercentile(r, [2.5, 97.5]).tolist()


def variant_returns(o: pd.DataFrame, c: pd.DataFrame, f: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Holding-interval returns dated at signal day t. o, c: raw open/close (dates x names); f: split factor on
    each session (new shares per old share, 1.0 otherwise). A price on a later session is restated into day-t share
    units by multiplying by the cumulative split factor in between."""
    f1 = f.shift(-1)
    f2 = f1 * f.shift(-2)
    return {
        "A": c.shift(-1) * f1 / c - 1.0,                      # close t -> close t+1
        "D": c.shift(-1) * f1 / c - 1.0,                      # same interval, different signal
        "B": (o.shift(-2) * f2) / (o.shift(-1) * f1) - 1.0,   # open t+1 -> open t+2
        "C": (c.shift(-2) * f2) / (c.shift(-1) * f1) - 1.0,   # close t+1 -> close t+2
    }


def main() -> None:
    import pit_panel as pp
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", type=Path, default=BARS)
    ap.add_argument("--boot", type=int, default=5000)
    ap.add_argument("--dry-run", action="store_true", help="coverage only: no returns are computed or printed")
    args = ap.parse_args()
    rng = np.random.default_rng(SEED)

    pit = pp.load_pit(start="2025-11-01", end=WINDOW[1], confirm=True, strict=False)
    dates = pd.DatetimeIndex([d for d in pit.sessions if d >= pd.Timestamp("2025-11-01")])
    names = sorted(pit.frames)
    o, c = wide(pit.frames, "Open", dates), wide(pit.frames, "Close", dates)
    mem = wide(pit.frames, "Member", dates).fillna(False).astype(bool)
    spread = wide(pit.frames, "SpreadEst", dates)
    f = pd.DataFrame(1.0, index=dates, columns=names)
    for r in pit.splits.itertuples(index=False):
        if r.date in f.index and r.ticker in f.columns:
            f.loc[r.date, r.ticker] *= r.factor

    snaps, coverage = {}, {"bar_files": 0, "securities_without_bars": []}
    for isin in names:
        p = args.bars / f"{isin}.parquet"
        if p.exists():
            coverage["bar_files"] += 1
            snaps[isin] = snapshot_from_bars(pd.read_parquet(p))
        elif mem.loc[WINDOW[0]:, isin].any():
            coverage["securities_without_bars"].append(isin)
    snap = pd.DataFrame({k: v["price"].reindex(dates) for k, v in snaps.items()}).reindex(columns=names)
    labels = pd.concat([v["label"] for v in snaps.values()]) if snaps else pd.Series(dtype=str)
    coverage["snapshot_label_counts"] = labels.value_counts().to_dict()

    if args.dry_run:
        w = mem.loc[WINDOW[0]:WINDOW[1]]
        s = snap.loc[WINDOW[0]:WINDOW[1]].notna() & w
        print({"sessions": len(w), "members_per_day": float(w.sum(1).mean()),
               "members_with_snapshot_per_day": float(s.sum(1).mean()),
               "bar_files": coverage["bar_files"], "members_without_bars": len(coverage["securities_without_bars"]),
               "labels": coverage["snapshot_label_counts"]})
        return

    prev_adj = c.shift(1) / f                                  # previous close in day-t share units
    sig_close = c / prev_adj - 1.0
    sig_340 = snap / prev_adj - 1.0
    win = (dates >= pd.Timestamp(WINDOW[0])) & (dates <= pd.Timestamp(WINDOW[1]))
    rets = variant_returns(o, c, f)

    # costs: half trailing spread at entry and exit + SEC rate on exit (rate in force on the exit session)
    fees = bc._fee_rows(bc.load_sell_fee_table())
    sec_rate = pd.Series([bc.sell_fees(d, 1.0, 0.0, fees) for d in dates], index=dates)   # notional 1, no shares
    half = spread.shift(1) / 2.0                               # engine convention: previous session's estimate
    cost = {"A": half + half.shift(-1) + sec_rate.shift(-1).to_numpy()[:, None],
            "D": half + half.shift(-1) + sec_rate.shift(-1).to_numpy()[:, None],
            "B": half.shift(-1) + half.shift(-2) + sec_rate.shift(-2).to_numpy()[:, None],
            "C": half.shift(-1) + half.shift(-2) + sec_rate.shift(-2).to_numpy()[:, None]}
    signals = {"A": sig_close, "D": sig_340, "B": sig_close, "C": sig_close}

    res: dict = {"preregistration": f"research/{TAG}_preregistration.md", "window": WINDOW,
                 "trials_after_this_study": 35, "coverage": coverage}
    baskets = {}
    # every variant must have a 3:40 snapshot so all four use the same day-by-day universe
    has_snap = snap.notna()
    for v in "ABCD":
        elig = mem & has_snap
        elig = elig & pd.DataFrame(np.repeat(win[:, None], len(names), axis=1), index=dates, columns=names)
        b = basket_excess(signals[v][elig], rets[v], elig, cost[v])
        top = basket_excess(signals[v][elig], rets[v], elig, cost[v], bottom=False)
        baskets[v] = b
        res[v] = {"gross": nw_stat(b["gross"]), "net": nw_stat(b["net"]),
                  "long_short_gross": nw_stat(b["gross"] - top["gross"].reindex(b.index)),
                  "top_decile_gross": nw_stat(top["gross"]), "avg_names": float(b["k"].mean()),
                  "avg_universe": float(b["n"].mean())}

    common = baskets["D"].index.intersection(baskets["B"].index).intersection(baskets["A"].index).intersection(
        baskets["C"].index)
    d_b = baskets["D"].loc[common, "gross"] - baskets["B"].loc[common, "gross"]
    res["primary_D_minus_B"] = nw_stat(d_b)
    res["primary_decision"] = {
        "mean_positive": bool(res["primary_D_minus_B"]["mean"] > 0),
        "nw_t_ge_2": bool(res["primary_D_minus_B"]["nw_t"] >= 2.0),
        "D_net_positive": bool(res["D"]["net"]["mean"] > 0)}
    res["primary_decision"]["preclose_adds_value"] = all(res["primary_decision"].values())

    num = (baskets["D"].loc[common, "gross"] - baskets["C"].loc[common, "gross"]).to_numpy()
    den = (baskets["A"].loc[common, "gross"] - baskets["C"].loc[common, "gross"]).to_numpy()
    res["capture_ratio"] = {"point": float(num.mean() / den.mean()) if den.mean() != 0 else float("nan"),
                            "ci95": block_boot_ratio(num, den, args.boot, rng)}
    rho, overlap = [], []
    for d in common:
        a, b = sig_close.loc[d], sig_340.loc[d]
        ok = mem.loc[d] & a.notna() & b.notna()
        rho.append(a[ok].rank().corr(b[ok].rank()))
        sa, sb = set(baskets["A"].loc[d, "names"]), set(baskets["D"].loc[d, "names"])
        overlap.append(len(sa & sb) / max(len(sa), 1))
    res["signal_agreement"] = {"spearman_mean": float(np.nanmean(rho)), "basket_overlap_mean": float(np.mean(overlap))}
    res["monthly_D_minus_B_bp"] = {str(k): float(v * 1e4) for k, v in d_b.groupby(d_b.index.to_period("M")).mean().items()}
    res["sessions"] = int(len(common))

    (OUT / f"{TAG}_results.json").write_text(json.dumps(res, indent=2, default=str))
    pd.DataFrame({v: baskets[v]["gross"] for v in "ABCD"}).to_csv(OUT / f"{TAG}_daily_gross.csv")
    print(json.dumps({k: v for k, v in res.items() if k not in ("coverage",)}, indent=1, default=str)[:4000])
    print("coverage:", {k: (len(v) if isinstance(v, list) else v) for k, v in coverage.items()})


if __name__ == "__main__":
    main()
