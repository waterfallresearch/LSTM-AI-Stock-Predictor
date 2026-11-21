"""Single evaluation of the PIT next-open study (research/pit_nextopen_2026-11-20_preregistration.md).

    python pit_evaluate.py [--shuffles 500] [--boot 5000] [--workers 8]

Two arms (amendment 6): F = fixed cutoff 0.25 (the preregistered primary), A = cutoff chosen per fold on that
fold's validation forecasts. Run ONCE, after all 27 jobs in wf_pit/ exist and the pre-close study's results are
written (its 4 Sharpes are part of the N = 40 trial pool). Writes research/pit_nextopen_2026-11-20_results.json and
trades CSVs. Refuses to overwrite an existing results file (a second evaluation would be a new trial).
"""
from __future__ import annotations

import argparse
import glob
import json
import re
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

import backtest_core as bc
import pit_panel as pp
from audit_backtest import block_bootstrap, deflated_sharpe, segment

ROOT = Path(__file__).resolve().parent
WF = ROOT / "wf_pit"
TAG = "pit_nextopen_2026-11-20"
SEED = 20261120
HZ = list(bc.PERIODS)
START, END = "2016-01-01", "2024-12-31"
N_TRIALS = 40          # amendment 6: 39 + the adaptive-cutoff arm
GRID = [0.20, 0.25, 0.30, 0.35]
BASE_CUT = 0.25


def params(**kw) -> bc.StrategyParams:
    return bc.StrategyParams.pit(initial_value=1_000_000.0, sell_fee_table=bc.load_sell_fee_table(), **kw)


# ----------------------------------------------------------------------------- signals

def load_forecasts(split: str = "test") -> pd.DataFrame:
    frames = []
    for f in sorted(glob.glob(str(WF / "forecasts" / f"Y*_s*_{split}.csv.gz"))):
        m = re.search(r"Y(\d+)_s(\d+)_", Path(f).name)
        df = pd.read_csv(f, parse_dates=["Date"])
        df["Year"], df["Seed"] = int(m.group(1)), int(m.group(2))
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def ensemble(df: pd.DataFrame) -> pd.DataFrame:
    """p = mean of seed means; sigma = sqrt(mean within-seed variance + variance across seed means). Keyed by fold
    Year too, because validation windows of different folds overlap."""
    df = df.copy()
    for h in HZ:
        df[f"_v_{h}"] = df[f"Pred_Prob_Std_{h}"] ** 2
    g = df.groupby(["Year", "Date", "isin"], sort=False)
    out = pd.DataFrame(index=g.size().index)
    for h in HZ:
        out[f"Pred_Prob_{h}"] = g[f"Pred_Prob_{h}"].mean()
        out[f"Pred_Prob_Std_{h}"] = np.sqrt(g[f"_v_{h}"].mean() + g[f"Pred_Prob_{h}"].var(ddof=0).fillna(0.0))
    return out.reset_index()


def to_scores(long: pd.DataFrame) -> dict[str, pd.DataFrame]:
    cols = [f"Pred_Prob_{h}" for h in HZ] + [f"Pred_Prob_Std_{h}" for h in HZ]
    return {k: g.set_index("Date").sort_index()[cols] for k, g in long.groupby("isin")}


def shift_scores(ens: pd.DataFrame, cut: dict[int, float]) -> pd.DataFrame:
    """adj > c  <=>  (p + 0.25 - c) - sigma > 0.25: one shift per test year, identical across horizons, so the
    best-horizon choice and the ranking among candidates are unchanged."""
    e = ens.copy()
    for y, c in cut.items():
        m = e["Year"] == y
        for h in HZ:
            e.loc[m, f"Pred_Prob_{h}"] += BASE_CUT - c
    return e


def wide(pit: pp.PitData, frame: str, col: str) -> pd.DataFrame:
    src = pit.adjusted if frame == "adjusted" else pit.frames
    return pd.DataFrame({k: v[col] for k, v in src.items()}).sort_index()


def ranking_scores(score: pd.DataFrame, member: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Cross-sectional percentile rank among members, in the 1m horizon only, sigma 0 (preregistered comparators)."""
    s = score.where(member.reindex_like(score).fillna(False).astype(bool))
    rk = s.rank(axis=1, pct=True)
    out = {}
    for k in rk.columns:
        d = pd.DataFrame(index=rk.index)
        for h in HZ:
            d[f"Pred_Prob_{h}"] = rk[k] if h == "1m" else np.nan
            d[f"Pred_Prob_Std_{h}"] = 0.0
        out[k] = d[rk[k].notna()]
    return out


def comparator_scores(pit: pp.PitData) -> dict[str, dict[str, pd.DataFrame]]:
    tr = wide(pit, "adjusted", "TrClose")
    mem = wide(pit, "frames", "Member")
    ffill = tr.ffill()
    lag = lambda n: ffill.shift(n)                                            # noqa: E731
    return {"MOM12-1": ranking_scores(lag(21) / lag(252) - 1, mem),
            "MOM6-1": ranking_scores(lag(21) / lag(126) - 1, mem),
            "REV1M": ranking_scores(-(tr / lag(21) - 1), mem)}


def panel_for(pit: pp.PitData, scores, spread_mult: float = 1.0) -> bc.Panel:
    frames = pit.frames
    if spread_mult != 1.0:
        frames = {k: v.assign(SpreadEst=v["SpreadEst"] * spread_mult) for k, v in frames.items()}
    tmp = pp.PitData(frames, pit.adjusted, pit.splits, pit.dividends, pit.settlements, pit.spy, pit.sessions, pit.end)
    return pp.build_pit_panel(tmp, scores, start=START)


def window_panel(pit: pp.PitData, scores, start, end) -> bc.Panel:
    """Panel restricted to [start, end]; `end` is before the test year, so no test-year price is read."""
    return bc.build_panel(pp.attach_scores(pit.frames, scores), start=start, end=end, splits=pit.splits,
                          dividends=pit.dividends[["ex_date", "ticker", "cash"]],
                          settlements=pit.settlements[["date", "ticker", "cash_per_share", "successor_ticker",
                                                       "successor_shares"]])


def pick_cutoff(sharpes: dict[float, float | None]) -> float:
    """Highest finite Sharpe; ties or no finite value -> BASE_CUT."""
    fin = {c: v for c, v in sharpes.items() if v is not None and np.isfinite(v)}
    if not fin:
        return BASE_CUT
    top = max(fin.values())
    best = [c for c, v in fin.items() if v == top]
    return best[0] if len(best) == 1 else BASE_CUT


def choose_cutoffs(pit: pp.PitData, val_ens: pd.DataFrame, metas: list[dict], p0) -> dict:
    """Amendment 6: per fold, the GRID cutoff with the highest after-cost daily Sharpe on the validation window."""
    out = {}
    for y in sorted(val_ens["Year"].unique()):
        d = next(m["dates"] for m in metas if m["year"] == y)
        end = pit.sessions[pit.sessions < pd.Timestamp(d["test_start"])][-1]
        pn = window_panel(pit, to_scores(val_ens[val_ens["Year"] == y]), d["val_start"], end)
        sh = {}
        for c in GRID:
            res = bc.run_strategy(pn, replace(p0, min_accepted=c))
            v = bc.sharpe(bc.daily_returns(res.equity))
            sh[c] = {"sharpe": float(v) if np.isfinite(v) else None, "trades": int(len(res.trades))}
        out[int(y)] = {"chosen": pick_cutoff({c: v["sharpe"] for c, v in sh.items()}), "validation": sh,
                       "val_window": [d["val_start"], str(end.date())]}
    return out


# ----------------------------------------------------------------------------- benchmarks

def spy_tr_equity(pit: pp.PitData, dates, v0: float) -> np.ndarray:
    tr = pit.spy["tr_index"].reindex(pd.DatetimeIndex(dates)).ffill().to_numpy()
    return v0 * tr / tr[0]


def ew_members(pit: pp.PitData, dates, v0: float) -> np.ndarray:
    tr = wide(pit, "adjusted", "TrClose").reindex(pd.DatetimeIndex(dates))
    mem = wide(pit, "frames", "Member").reindex(tr.index).fillna(False).astype(bool)
    r = tr / tr.shift(1) - 1
    held = mem.shift(1, fill_value=False) & r.notna()
    daily = r.where(held).sum(1) / held.sum(1).clip(lower=1)
    daily.iloc[0] = 0.0
    return v0 * np.cumprod(1 + daily.to_numpy())


def stats(eq: np.ndarray, v0: float) -> dict:
    r = bc.daily_returns(eq)
    return {"total_return": float(eq[-1] / v0 - 1), "cagr": float((eq[-1] / v0) ** (252 / (len(eq) - 1)) - 1),
            "sharpe": bc.sharpe(r), "max_drawdown": bc.max_drawdown(eq)}


# ----------------------------------------------------------------------------- shuffle workers

_PANEL = None
_P = None


def _init(panel, p):
    global _PANEL, _P
    _PANEL, _P = panel, p


def _shuffle(seed: int) -> float:
    res = bc.run_strategy(_PANEL, _P, rng=np.random.default_rng(seed), shuffle_signals=True)
    return float(res.equity[-1] / _P.initial_value - 1)


def sr_ci(r: np.ndarray, boot: int, rng) -> list:
    b = block_bootstrap(r, boot, 20, rng)
    return np.percentile(np.sqrt(252) * b.mean(1) / b.std(1, ddof=1), [2.5, 97.5]).tolist()


def paired_sr_diff_ci(r1: np.ndarray, r2: np.ndarray, boot: int, rng, block: int = 20) -> list:
    """95% CI of Sharpe(r1) - Sharpe(r2), the same resampled blocks for both series."""
    n = min(len(r1), len(r2))
    r1, r2 = r1[:n], r2[:n]
    nb = int(np.ceil(n / block))
    starts = rng.integers(0, n - block + 1, size=(boot, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(boot, -1)[:, :n]
    a, b = r1[idx], r2[idx]
    d = np.sqrt(252) * (a.mean(1) / a.std(1, ddof=1) - b.mean(1) / b.std(1, ddof=1))
    return np.percentile(d, [2.5, 97.5]).tolist()


def trial_pool(extra: list[float]) -> np.ndarray:
    sr = [json.load(open(f))["strategy"]["sharpe"] for f in sorted(glob.glob(str(ROOT / "research/trials_2026-11-19/*/*.json")))]
    sr += [v["sharpe"] for v in json.load(open(ROOT / "research/audit_2026-11-19_results.json"))["runs"].values()]
    w = json.load(open(ROOT / "research/walkforward_2026-11-19_results.json"))
    sr += [w["primary"]["sharpe"], w["secondary_nested_threshold"]["sharpe"]]
    sr += [json.load(open(ROOT / "research/latency_2026-11-20_results.json"))["walkforward"]["portfolio"]["B_next_open"]["sharpe"]]
    pc = json.load(open(ROOT / "research/preclose_2026-11-20_results.json"))
    sr += [pc[v]["net"]["sharpe"] for v in "ABCD"]
    sr += extra
    if len(sr) != N_TRIALS:
        raise RuntimeError(f"trial pool has {len(sr)} Sharpes, preregistered N = {N_TRIALS}")
    return np.array([s for s in sr if s is not None and np.isfinite(s)])


# ----------------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shuffles", type=int, default=500)
    ap.add_argument("--boot", type=int, default=5000)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    out_json = ROOT / "research" / f"{TAG}_results.json"
    if out_json.exists():
        raise SystemExit(f"{out_json.name} exists: the study was already evaluated once.")
    metas = [json.load(open(f)) for f in sorted(glob.glob(str(WF / "meta" / "*.json")))]
    if len(metas) != 27:
        raise SystemExit(f"{len(metas)}/27 jobs finished")
    spec = json.loads((WF / "feature_spec.json").read_text())
    assert all(m["features_sha256"] == spec["features_sha256"] for m in metas)

    rng = np.random.default_rng(SEED)
    pit = pp.load_pit(end=END, strict=True)
    p0 = params()
    v0 = p0.initial_value

    test = load_forecasts("test")
    ens = ensemble(test)
    cuts = choose_cutoffs(pit, ensemble(load_forecasts("val")), metas, p0)
    arm_scores = {"F": to_scores(ens), "A": to_scores(shift_scores(ens, {y: v["chosen"] for y, v in cuts.items()}))}
    panels = {k: panel_for(pit, s) for k, s in arm_scores.items()}
    dates = panels["F"].dates
    spy = spy_tr_equity(pit, dates, v0)
    spy_r = bc.daily_returns(spy)
    ew = ew_members(pit, dates, v0)
    out: dict = {"preregistration": f"research/{TAG}_preregistration.md", "seed": SEED,
                 "features_sha256": spec["features_sha256"], "features_file_sha256": spec["features_file_sha256"],
                 "window": [str(dates[0].date()), str(dates[-1].date())], "securities": len(panels["F"].tickers),
                 "params": {k: v for k, v in asdict(p0).items() if k != "sell_fee_table"},
                 "spy_tr": stats(spy, v0), "ew_members": stats(ew, v0), "data_report": pit.report,
                 "folds": [{k: m[k] for k in ["year", "seed_index", "n_train", "n_val", "best_epoch", "best_val_auc",
                                              "test_auc", "minutes", "train_rows_dropped_label_past_last_bar"]}
                           for m in metas],
                 "adaptive_cutoffs": cuts}

    def run(pn, p):
        res = bc.run_strategy(pn, p)
        s = bc.summarize(res, v0)
        s.update(cost_breakdown=res.cost_breakdown, spread_fallbacks=res.spread_fallbacks,
                 cap_blocked=res.cap_blocked, cap_shrunk=res.cap_shrunk, dividends=res.dividends)
        return res, s

    def yby(eq):
        return {int(y): segment(eq, dates, pd.Timestamp(f"{y - 1}-12-31"), pd.Timestamp(f"{y}-12-31"))["total_return"]
                for y in range(2016, 2025)}

    arm_res, arm_sum, arm_r = {}, {}, {}
    for k in "FA":
        arm_res[k], arm_sum[k] = run(panels[k], p0)
        arm_res[k].trades.to_csv(ROOT / "research" / f"{TAG}_trades_{k}.csv", index=False)
        arm_r[k] = bc.daily_returns(arm_res[k].equity)

    comp, comp_r = {}, {}
    for name, sc in comparator_scores(pit).items():
        res, s = run(panel_for(pit, sc), replace(p0, min_accepted=0.80))
        comp[name], comp_r[name] = s, bc.daily_returns(res.equity)
    out["comparators"] = comp
    best = max(comp, key=lambda k: comp[k]["sharpe"] if np.isfinite(comp[k]["sharpe"]) else -np.inf)
    pool = trial_pool([arm_sum["F"]["sharpe"], arm_sum["A"]["sharpe"]]
                      + [comp[k]["sharpe"] for k in ["MOM12-1", "MOM6-1", "REV1M"]])
    spy_y = yby(spy)

    for k in "FA":
        s, r, res = arm_sum[k], arm_r[k], arm_res[k]
        t: dict = {}
        t["1_cagr_vs_spy_tr"] = {"strategy": s["cagr"], "spy_tr": out["spy_tr"]["cagr"],
                                 "pass": bool(s["cagr"] > out["spy_tr"]["cagr"])}
        with ProcessPoolExecutor(a.workers, initializer=_init, initargs=(panels[k], p0)) as ex:
            null = np.array(list(ex.map(_shuffle, [SEED + 1 + i for i in range(a.shuffles)], chunksize=4)))
        p_sh = float((1 + np.sum(null >= s["total_return"])) / (1 + a.shuffles))
        t["2_shuffle_control"] = {"n": a.shuffles, "p_value": p_sh,
                                  "null_p5_p50_p95": np.percentile(null, [5, 50, 95]).tolist(), "pass": p_sh <= 0.05}
        ci = sr_ci(r, a.boot, rng)
        t["3_bootstrap_sharpe"] = {"sharpe": s["sharpe"], "ci95": ci, "pass": bool(ci[0] > 0)}
        rr = pd.Series(r)
        dsr = deflated_sharpe(float(r.mean() / r.std(ddof=1)), pool / np.sqrt(252), r.size, float(rr.skew()),
                              float(rr.kurt() + 3))
        t["4_deflated_sharpe"] = {**dsr, "pass": bool(dsr["dsr"] >= 0.95)}
        dci = paired_sr_diff_ci(r, comp_r[best], a.boot, rng)
        t["5_vs_best_ranking"] = {"best": best, "best_sharpe": comp[best]["sharpe"], "lstm_sharpe": s["sharpe"],
                                  "sharpe_diff_ci95": dci,
                                  "pass": bool(s["sharpe"] > comp[best]["sharpe"] and dci[0] > 0)}
        t14 = all(t[x]["pass"] for x in ["1_cagr_vs_spy_tr", "2_shuffle_control", "3_bootstrap_sharpe",
                                         "4_deflated_sharpe"])
        verdict = ("Edge supported" if t14 and t["5_vs_best_ranking"]["pass"] else
                   "Ranking informative but not distinct from simple factors" if t14 else "Edge not supported")
        sec: dict = {"year_by_year": {y: {"strategy": v, "spy_tr": spy_y[y]} for y, v in yby(res.equity).items()}}
        _, sec["cost_stress_2x_spread_impact2"] = run(panel_for(pit, arm_scores[k], spread_mult=2.0),
                                                     replace(p0, impact_k=2.0))
        pnl = res.trades["PnL$"].sort_values(ascending=False) if len(res.trades) else pd.Series(dtype=float)
        v_wo = res.equity[-1] - pnl.head(3).sum()
        yrs = (len(res.equity) - 1) / 252
        sec["remove_top3"] = {"top3_pnl": pnl.head(3).round(2).tolist(),
                              "cagr_without_top3": float((v_wo / v0) ** (1 / yrs) - 1) if v_wo > 0 else -1.0}
        sec["beta_vs_spy_tr"] = float(np.cov(r, spy_r[: r.size])[0, 1] / np.var(spy_r[: r.size], ddof=1))
        out[f"arm_{k}"] = {"summary": s, "tests": t, "verdict": verdict, "secondary": sec}

    # Arm F only (preregistered secondary): single seeds and the timing diagnostic
    out["arm_F"]["secondary"]["single_seed_sharpe"] = {
        int(k): bc.summarize(bc.run_strategy(panel_for(pit, to_scores(ensemble(test[test["Seed"] == k]))), p0),
                             v0)["sharpe"]
        for k in sorted(test["Seed"].unique())}
    _, out["arm_F"]["secondary"]["timing_next_close"] = run(panels["F"], replace(p0, fill="next_close"))
    out["sector_exposure"] = "not available: the PIT layer has no point-in-time sector classification"

    # ---- amendment 6: comparison and confirmation recipe
    dci = paired_sr_diff_ci(arm_r["A"], arm_r["F"], a.boot, rng)
    stress = {k: out[f"arm_{k}"]["secondary"]["cost_stress_2x_spread_impact2"]["sharpe"] for k in "FA"}
    ya, yf = yby(arm_res["A"].equity), yby(arm_res["F"].equity)
    out["comparison_A_minus_F"] = {
        "sharpe_diff": arm_sum["A"]["sharpe"] - arm_sum["F"]["sharpe"], "sharpe_diff_ci95": dci,
        "cagr_diff": arm_sum["A"]["cagr"] - arm_sum["F"]["cagr"],
        "max_drawdown": {k: arm_sum[k]["max_drawdown"] for k in "AF"},
        "annual_turnover": {k: arm_sum[k]["annual_turnover"] for k in "AF"},
        "cost_breakdown": {k: arm_sum[k]["cost_breakdown"] for k in "AF"},
        "stress_sharpe": stress, "year_by_year_diff": {y: ya[y] - yf[y] for y in ya}}
    a_ok = out["arm_A"]["verdict"] == "Edge supported" and dci[0] > 0 and stress["A"] >= stress["F"]
    recipe = "A" if a_ok else ("F" if out["arm_F"]["verdict"] == "Edge supported" else None)
    out["confirmation_recipe"] = recipe or "none: 2025 stays sealed"
    out["verdict"] = out["arm_F"]["verdict"]          # the preregistered primary
    out["trials"] = {"N": N_TRIALS, "after_this_study_including_timing_diagnostic": N_TRIALS + 1}

    out_json.write_text(json.dumps(out, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    print(f"window {out['window']}  SPY TR CAGR {out['spy_tr']['cagr']:+.1%}  EW {out['ew_members']['cagr']:+.1%}")
    print("adaptive cutoffs", {y: v["chosen"] for y, v in cuts.items()})
    for k in "FA":
        s = arm_sum[k]
        print(f"ARM {k}: CAGR {s['cagr']:+.1%} Sharpe {s['sharpe']:.2f} MDD {s['max_drawdown']:+.1%} "
              f"trades {s['trades']} -> {out[f'arm_{k}']['verdict']}")
        for t, v in out[f"arm_{k}"]["tests"].items():
            print(f"   TEST {t:22s} {'PASS' if v['pass'] else 'FAIL'}")
    for k, v in comp.items():
        print(f"  {k:8s} CAGR {v['cagr']:+.1%} Sharpe {v['sharpe']:.2f}")
    print("A-F Sharpe diff CI", dci, "| confirmation recipe:", out["confirmation_recipe"])


if __name__ == "__main__":
    main()
