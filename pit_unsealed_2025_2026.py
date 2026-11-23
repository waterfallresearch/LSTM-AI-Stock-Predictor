"""Owner-unsealed, descriptive run of the restored LSTM rule (p - sigma > 0.25) on 2025-01-02 -> 2026-11-18.
Design: research/pit_lstm_unsealed_2025_2026_preregistration.md (written before any forecast here existed).

    python pit_unsealed_2025_2026.py prepare      # extend frozen features to NEW_END + parity check vs wf_pit/features.parquet
    python pit_unsealed_2025_2026.py train        # 2 folds x 3 seeds, frozen pit_walk_forward.run_job (--comparison path)
    python pit_unsealed_2025_2026.py score        # once; refuses to overwrite

Nothing in the frozen modules is edited: their 2024 end date and the confirmation guard are overridden in-process
only, so the unsealing is explicit here (confirm=True) and nowhere else.
"""
from __future__ import annotations

import argparse
import functools
import json
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

import pit_panel as pp
import pit_walk_forward as pit_wf

NEW_END = "2026-11-18"
TEST_START = pd.Timestamp("2025-01-02")
SEALED_END = pd.Timestamp("2025-11-18")
YEARS = (2025, 2026)
SEEDS = 3
OUT = pit_wf.ROOT / "wf_pit_unsealed_2025_2026"
FROZEN_FEATURES = pit_wf.ROOT / "wf_pit" / "features.parquet"
FROZEN_FEATURE_HASH = "f67687edae68f01af7cc5f639ac1f9ef153677773409ebd06567a68dc60dfc20"
BOOT_SEED = 20261123
TRIALS = 57


def load_pit_unsealed(**kw):
    kw.setdefault("end", NEW_END)
    return _ORIGINAL_LOAD_PIT(confirm=True, **kw)


_ORIGINAL_LOAD_PIT = pp.load_pit


# ----------------------------------------------------------------------------- features

def prepare() -> None:
    OUT.mkdir(exist_ok=True)
    if (OUT / "feature_spec.json").exists():
        sys.exit("Extended features already frozen.")
    if pit_wf.features_sha() != FROZEN_FEATURE_HASH:
        sys.exit("FEATURES differ from the frozen list")
    pit = load_pit_unsealed(strict=True)
    spyf = pit_wf.spy_features(pit.spy)
    parts, dropped = [], 0
    for isin, a in pit.adjusted.items():          # identical loop to pit_walk_forward.prepare
        f = pit.frames[isin]
        valid = a["AdjClose"].notna()
        a, mem = a[valid], f.loc[valid, "Member"]
        if len(a) < pit_wf.WINDOW + 2:
            continue
        d = pit_wf.security_features(a).join(spyf, how="left")
        d = d.replace([np.inf, -np.inf], np.nan)
        ok = d[pit_wf.FEATURES].notna().all(axis=1)
        dropped += int((~ok & mem).sum())
        d = d[ok]
        d.insert(0, "member", mem.reindex(d.index).astype(bool))
        d.insert(0, "isin", isin)
        parts.append(d.reset_index())
    df = pd.concat(parts, ignore_index=True)
    df[pit_wf.FEATURES] = df[pit_wf.FEATURES].astype(np.float32)

    # Parity: every development-period feature row must equal the frozen file.
    frozen = pd.read_parquet(FROZEN_FEATURES, columns=["isin", "Date", "member", *pit_wf.FEATURES])
    old = df.loc[df.Date <= pd.Timestamp(pit_wf.END), ["isin", "Date", "member", *pit_wf.FEATURES]]
    merged = frozen.merge(old, on=["isin", "Date"], how="outer", suffixes=("_f", "_n"), indicator=True)
    only = merged["_merge"].value_counts().to_dict()
    both = merged[merged["_merge"] == "both"]
    worst = {}
    for c in pit_wf.FEATURES:
        a, b = both[f"{c}_f"].to_numpy(np.float64), both[f"{c}_n"].to_numpy(np.float64)
        worst[c] = float(np.max(np.abs(a - b) / np.maximum(1.0, np.abs(a))))
    member_mismatch = int((both["member_f"] != both["member_n"]).sum())
    parity = {"rows_frozen_only": int(only.get("left_only", 0)), "rows_new_only": int(only.get("right_only", 0)),
              "rows_both": int(len(both)), "member_mismatch": member_mismatch,
              "max_scaled_abs_diff": max(worst.values()), "worst_feature": max(worst, key=worst.get)}
    print(json.dumps(parity, indent=1), flush=True)
    if parity["rows_frozen_only"] or parity["rows_new_only"] or member_mismatch or parity["max_scaled_abs_diff"] > 1e-5:
        (OUT / "parity_failure.json").write_text(json.dumps({"parity": parity, "per_feature": worst}, indent=1))
        sys.exit("PARITY FAILED: extended features do not reproduce the frozen 2011-2024 file. Stop and report.")

    path = OUT / "features.parquet"
    df.to_parquet(path, index=False)
    spec = {"features": pit_wf.FEATURES, "features_sha256": pit_wf.features_sha(),
            "features_file_sha256": pit_wf.file_sha(path), "frozen_dev_file_sha256": pit_wf.file_sha(FROZEN_FEATURES),
            "code_sha256": pit_wf.file_sha(Path(__file__)), "end": NEW_END, "rows": len(df),
            "securities": int(df["isin"].nunique()), "member_rows_dropped_warmup_or_missing": dropped,
            "parity": parity, "frozen_utc": pd.Timestamp.now("UTC").isoformat()}
    (OUT / "feature_spec.json").write_text(json.dumps(spec, indent=1, default=str))


def load_extended():
    spec = json.loads((OUT / "feature_spec.json").read_text())
    if spec["features_sha256"] != pit_wf.features_sha() or pit_wf.file_sha(OUT / "features.parquet") != spec[
            "features_file_sha256"]:
        raise RuntimeError("Extended features changed after freezing")
    df = pd.read_parquet(OUT / "features.parquet")
    return {k: g.reset_index(drop=True) for k, g in df.groupby("isin", sort=True)}, spec


# ----------------------------------------------------------------------------- training

def job(year: int, k: int, threads: int) -> None:
    # Point the frozen runner at the extended inputs; the model/training code itself is untouched.
    pit_wf.END = NEW_END
    pit_wf.OUT = OUT
    pit_wf.load_frozen = load_extended
    pp.load_pit = load_pit_unsealed
    pit_wf.run_job(year, k, threads, comparison=True)


def train(workers: int, threads: int) -> None:
    load_extended()
    logs = OUT / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    meta_dir = OUT / "model_comparison" / "lstm" / "meta"
    jobs = [(y, k) for y in YEARS for k in range(SEEDS) if not (meta_dir / f"Y{y}_s{k}.json").exists()]
    print(f"[{time.strftime('%H:%M:%S')}] {len(jobs)} jobs", flush=True)
    running, failed = [], []
    while jobs or running:
        while jobs and len(running) < workers:
            y, k = jobs.pop(0)
            log = open(logs / f"Y{y}_s{k}.log", "w")
            cmd = [sys.executable, str(Path(__file__)), "job", "--year", str(y), "--seed-index", str(k),
                   "--threads", str(threads)]
            running.append((subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=pit_wf.ROOT), (y, k), log))
        time.sleep(10)
        for item in running[:]:
            p, yk, log = item
            if p.poll() is not None:
                log.close()
                running.remove(item)
                if p.returncode:
                    failed.append(yk)
                print(f"[{time.strftime('%H:%M:%S')}] Y{yk[0]} s{yk[1]} {'ok' if not p.returncode else 'FAILED'}",
                      flush=True)
    print("done; failed:", failed, flush=True)


# ----------------------------------------------------------------------------- scoring

def pooled_forecasts():
    import pit_evaluate as prior
    from pit_model_comparison import KEYS, PROBS
    root = OUT / "model_comparison" / "lstm"
    spec = json.loads((OUT / "feature_spec.json").read_text())
    frames, aucs = [], {}
    std_cols = [f"Pred_Prob_Std_{h}" for h in prior.HZ]
    labels = [f"Class_{h}" for h in prior.HZ]
    for year in YEARS:
        fold = []
        for k in range(SEEDS):
            meta = json.loads((root / "meta" / f"Y{year}_s{k}.json").read_text())
            if (meta["seed"], meta["corrected_labels"], meta["features_file_sha256"]) != (
                    1000 * year + k, True, spec["features_file_sha256"]):
                raise ValueError(f"Unregistered fold metadata Y{year}_s{k}")
            f = pd.read_csv(root / "forecasts" / f"Y{year}_s{k}_test.csv.gz", parse_dates=["Date"])
            if not np.isfinite(f[std_cols].to_numpy()).all() or (f[std_cols] < 0).any(axis=None):
                raise ValueError("Invalid MC standard deviations")
            aucs[f"Y{year}_s{k}"] = fold_auc(f, prior.HZ)
            fold.append(f.set_index(KEYS, verify_integrity=True).sort_index())
        if not all(x.index.equals(fold[0].index) for x in fold):
            raise ValueError(f"Seed prediction keys differ in {year}")
        pooled = prior.ensemble(pd.concat([x[PROBS + std_cols] for x in fold]).reset_index().assign(Year=year))
        pooled = pooled.merge(fold[0][labels].reset_index(), on=KEYS, how="left", validate="one_to_one")
        frames.append(pooled)
    out = pd.concat(frames, ignore_index=True)
    out = out[(out.Date >= TEST_START) & (out.Date <= pd.Timestamp(NEW_END))]
    return out, aucs


def fold_auc(frame, horizons):
    from sklearn.metrics import roc_auc_score
    res = {}
    for h in horizons:
        m = frame[f"Class_{h}"].notna()
        y = frame.loc[m, f"Class_{h}"]
        res[h] = float(roc_auc_score(y, frame.loc[m, f"Pred_Prob_{h}"])) if y.nunique() == 2 else None
    return res


def build(pit, scores, spread_mult=1.0):
    frames = pit.frames
    if spread_mult != 1.0:
        frames = {k: v.assign(SpreadEst=v["SpreadEst"] * spread_mult) for k, v in frames.items()}
    tmp = pp.PitData(frames, pit.adjusted, pit.splits, pit.dividends, pit.settlements, pit.spy, pit.sessions, pit.end)
    return pp.build_pit_panel(tmp, scores, start=TEST_START, confirm=True)


def common_rows(pit, pooled, params):
    """Head-to-head common trading eligibility (pit_model_comparison.portfolio_inputs), on the unsealed panel."""
    import pit_evaluate as prior
    from pit_model_comparison import KEYS
    bc = prior.bc
    elig = build(pit, {})
    allowed = pd.DataFrame(np.stack([bc._eligible_mask(elig, i, params) for i in range(len(elig.dates))]),
                           index=elig.dates, columns=elig.tickers).stack()
    mom = prior.wide(pit, "adjusted", "TrClose")
    mom = (mom.shift(21) / mom.shift(126) - 1).stack()
    keys = pd.MultiIndex.from_frame(pooled[KEYS])
    valid = allowed.reindex(keys, fill_value=False).to_numpy() & np.isfinite(mom.reindex(keys).to_numpy())
    return pooled.loc[valid].copy(), {"pooled_rows": int(len(pooled)), "eligible_rows": int(valid.sum())}


def window_stats(equity, dates, lo, hi, v0):
    import pit_evaluate as prior
    dates = pd.DatetimeIndex(dates)
    idx = np.flatnonzero((dates >= lo) & (dates <= hi))
    start = idx[0] - 1 if idx[0] > 0 else None
    seg = equity[idx] if start is None else np.concatenate([[equity[start]], equity[idx]])
    base = v0 if start is None else equity[start]
    s = prior.stats(seg, base)
    s["sessions"] = int(len(idx))
    return s


def score() -> None:
    import pit_breadth as breadth
    import pit_evaluate as prior
    import pit_model_comparison as comparison
    from pit_model_comparison import KEYS, PROBS
    bc = prior.bc
    result_path = OUT / "results.json"
    if result_path.exists():
        raise FileExistsError("Scored once already: " + str(result_path))
    pooled, aucs = pooled_forecasts()
    pit = load_pit_unsealed(strict=True)
    control_params = prior.params(min_accepted=0., std_factor=0.)
    restored_params = replace(control_params, min_accepted=.25, std_factor=1.)
    common, coverage = common_rows(pit, pooled, control_params)
    arms = {"restored": (prior.to_scores(common), restored_params),
            "control": (comparison.ranked_offers(common[KEYS + PROBS]), control_params)}
    v0 = control_params.initial_value
    metrics, equity, trades = {}, {}, {}
    dates = None
    for arm, (scores, params) in arms.items():
        panel = build(pit, scores)
        cal = pd.DatetimeIndex(panel.dates)
        if cal[0] != TEST_START or cal[-1] != pd.Timestamp(NEW_END):
            raise ValueError(f"Unexpected calendar {cal[0].date()} .. {cal[-1].date()}")
        if dates is not None and not cal.equals(dates):
            raise ValueError("Arm calendars differ")
        dates = cal
        base = bc.run_strategy(panel, params, confirm=True)
        stress = bc.run_strategy(build(pit, scores, spread_mult=2), replace(params, impact_k=2), confirm=True)
        for res in (base, stress):
            comparison.verify_ledger(res, dates, v0)
        pruned = comparison.remove_top_three(base, dates)
        t = base.trades
        pnl = t["PnL$"] if len(t) else pd.Series(dtype=float)
        net_pnl = base.equity[-1] - v0
        metrics[arm] = {
            "net": bc.summarize(base, v0), "stress": bc.summarize(stress, v0), "pruned": prior.stats(pruned, v0),
            "costs": base.cost_breakdown,
            "horizon_counts": t["Horizon"].value_counts().to_dict() if len(t) else {},
            "top3_share_of_net_pnl": float(pnl.nlargest(3).sum() / net_pnl) if len(t) and net_pnl > 0 else None,
            "windows": {name: window_stats(base.equity, dates, lo, hi, v0) for name, (lo, hi) in {
                "full": (TEST_START, pd.Timestamp(NEW_END)),
                "sealed_2025-01-02_2025-11-18": (TEST_START, SEALED_END),
                "2025": (TEST_START, pd.Timestamp("2025-12-31")),
                "2026_ytd": (pd.Timestamp("2026-01-01"), pd.Timestamp(NEW_END))}.items()},
        }
        equity[arm], trades[arm] = base.equity, t
    spy = prior.spy_tr_equity(pit, dates, v0)
    equity["spy_tr"] = spy
    spy_metrics = {"net": prior.stats(spy, v0), "windows": {}}
    for name, (lo, hi) in {"full": (TEST_START, pd.Timestamp(NEW_END)),
                           "sealed_2025-01-02_2025-11-18": (TEST_START, SEALED_END),
                           "2025": (TEST_START, pd.Timestamp("2025-12-31")),
                           "2026_ytd": (pd.Timestamp("2026-01-01"), pd.Timestamp(NEW_END))}.items():
        spy_metrics["windows"][name] = window_stats(spy, dates, lo, hi, v0)

    returns = {k: bc.daily_returns(v) for k, v in equity.items()}
    n = len(returns["restored"])
    starts = np.random.default_rng(BOOT_SEED).integers(0, n - 19, size=(5000, (n + 19) // 20))
    idx = (starts[..., None] + np.arange(20)).reshape(5000, -1)[:, :n]
    boot = {k: np.sqrt(252) * r[idx].mean(axis=1) / r[idx].std(axis=1, ddof=1) for k, r in returns.items()}
    paired = {}
    for other in ("spy_tr", "control"):
        point = bc.sharpe(returns["restored"]) - bc.sharpe(returns[other])
        paired[other] = {"difference": float(point), "lower_95": float(np.quantile(boot["restored"] - boot[other], .05))}

    dev = pit_wf.ROOT / "wf_pit"
    old = json.loads((dev / "breadth/results.json").read_text())
    ranks = json.loads((dev / "price_ranks/results.json").read_text())
    rest = json.loads((dev / "model_comparison/rule_attribution/results.json").read_text())
    seeds = json.loads((dev / "model_comparison/seed_stability/results.json").read_text())
    matched = json.loads((dev / "model_comparison/matched_uncertainty/results.json").read_text())
    extras = [old["portfolios"][a]["net"]["sharpe"] for a in ("five", "broad")]
    extras += [ranks["arms"][a]["net"]["sharpe"] for a in ("momentum", "composite")]
    extras += [rest["portfolios"]["restored"]["net"]["sharpe"]]
    extras += [v["net"]["sharpe"] for v in seeds["seeds"].values()]
    extras += [matched["portfolios"][a]["net"]["sharpe"] for a in comparison.MODELS]
    extras += [metrics["restored"]["net"]["sharpe"]]
    pool = breadth.registered_trial_pool(extras)
    if len(pool) != TRIALS or not np.isfinite(pool).all():
        raise ValueError(f"Trial pool has {len(pool)} entries, expected {TRIALS}")
    r = pd.Series(returns["restored"])
    dsr = prior.deflated_sharpe(float(r.mean() / r.std()), pool / np.sqrt(252), len(r),
                                float(r.skew()), float(r.kurt() + 3))
    s_rest, s_spy = metrics["restored"]["net"]["sharpe"], spy_metrics["net"]["sharpe"]
    reading = ("consistent with the development result" if s_rest > s_spy and paired["spy_tr"]["lower_95"] > 0
               else "not consistent with the development result")
    result = {"window": [str(TEST_START.date()), NEW_END], "status": "owner-unsealed, descriptive, not a confirmation",
              "trials": TRIALS, "coverage": coverage, "fold_test_auc": aucs, "portfolios": metrics,
              "spy_tr": spy_metrics, "paired_sharpe": paired, "deflated_sharpe": dsr, "reading": reading,
              "code_sha256": pit_wf.file_sha(Path(__file__))}
    for arm in ("restored", "control"):
        trades[arm].to_csv(OUT / f"{arm}_trades.csv", index=False)
    pd.DataFrame({"Date": dates, **{k: v for k, v in equity.items()}}).to_csv(OUT / "equity.csv", index=False)
    result_path.write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps({"reading": reading, "paired": paired, "dsr": dsr.get("dsr")}, indent=1, default=str))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["prepare", "train", "job", "score"])
    ap.add_argument("--year", type=int)
    ap.add_argument("--seed-index", type=int, default=0)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--threads", type=int, default=5)
    a = ap.parse_args()
    if a.mode == "prepare":
        prepare()
    elif a.mode == "train":
        train(a.workers, a.threads)
    elif a.mode == "job":
        if a.year not in YEARS or a.seed_index not in range(SEEDS):
            ap.error("only the registered 2025/2026 folds and seeds 0-2")
        job(a.year, a.seed_index, a.threads)
    else:
        score()


if __name__ == "__main__":
    main()
