"""Locked price-rank composite vs six-month momentum, development only."""
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

import pit_breadth as breadth
import pit_evaluate as prior
from pit_model_comparison import remove_top_three


def signals(total, price, volume):
    """Return causal price-derived signals on the frozen development calendar."""
    returns = total / total.shift(1) - 1
    return (
        total.shift(21) / total.shift(126) - 1,
        (
            total.shift(21) / total.shift(252) - 1,
            1 - total.shift(1) / total.shift(21),
            -returns.rolling(63, min_periods=63).std().shift(1),
            (price * volume).rolling(20, min_periods=20).mean().shift(1),
        ),
    )


def schedules(panel, baseline, features, params):
    dates = pd.DatetimeIndex(panel.dates)
    control = baseline.reindex(index=dates, columns=panel.tickers).to_numpy()
    factors = np.stack([x.reindex(index=dates, columns=panel.tickers).to_numpy() for x in features])
    targets = {"momentum": {}, "composite": {}}
    ranks = {key: {} for key in targets}
    common_counts = []
    filters = replace(params, use_member_mask=False)
    for i in range(1, len(dates) - 1):
        if dates[i].month == dates[i + 1].month:
            continue
        eligible = prior.bc._eligible_mask(panel, i - 1, filters) & panel.member[i]
        eligible &= np.isfinite(control[i]) & np.isfinite(factors[:, i]).all(axis=0)
        names = np.flatnonzero(eligible)
        common_counts.append(len(names))
        composite = pd.DataFrame(factors[:, i, names].T).rank(pct=True).mean(axis=1).to_numpy()
        for arm, scores in (("momentum", control[i, names]), ("composite", composite)):
            ordered = sorted(range(len(names)), key=lambda j: (-scores[j], panel.tickers[names[j]]))
            ranking = names[ordered].tolist()
            ranks[arm][i] = scores[ordered], ranking
            targets[arm][i] = {j: 0.2 for j in ranking[:5]}
    return targets, ranks, common_counts


def evaluate(output):
    root = prior.ROOT
    if output.exists():
        raise RuntimeError("The price-rank output directory already exists")
    previous_path = root / "wf_pit/breadth/results.json"
    if breadth.sha256(previous_path) != "b53b3b90ee05be4ec14374e1f6996dd3a7647d5fdba064fd7904cb496d8562fd":
        raise ValueError("Breadth results differ from the registered predecessor fingerprint")
    previous = json.loads(previous_path.read_text())
    if previous["manifest"]["trial_count"] != 47 or previous["advance"]:
        raise ValueError("Breadth outcome does not match this preregistration")
    for file, expected in previous["manifest"]["trial_inputs_sha256"].items():
        if breadth.sha256(root / file) != expected:
            raise ValueError(f"Predecessor trial artifact changed: {file}")
    pool = breadth.registered_trial_pool([previous["portfolios"][arm]["net"]["sharpe"] for arm in ("five", "broad")])
    if len(pool) != 47 or not np.isfinite(pool).all():
        raise ValueError("Incomplete predecessor trials")
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=root)
    if dirty:
        raise ValueError("Use a clean scoring worktree")
    pit = prior.pp.load_pit(end=prior.END, strict=True)
    panel = prior.panel_for(pit, None)
    dates = pd.DatetimeIndex(panel.dates)
    p = prior.params(cost_bps=1.0)
    control, factors = signals(
        prior.wide(pit, "adjusted", "TrClose"), prior.wide(pit, "frames", "Close"),
        prior.wide(pit, "frames", "Volume"),
    )
    targets, ranks, counts = schedules(panel, control, factors, p)
    if len(counts) != 107 or min(counts) < 5 or dates[-1] != pd.Timestamp(prior.END):
        raise ValueError("Insufficient common eligibility or incomplete development calendar")
    files = [root / f for f in (
        "pit_price_ranks.py", "pit_breadth.py", "backtest_core.py", "pit_panel.py",
        "pit_evaluate.py", "pit_model_comparison.py", "audit_backtest.py", "research/pit_price_ranks_preregistration.md",
        "wf_pit/breadth/results.json", "wf_pit/model_comparison/evaluation/results.json",
    )]
    tables = root / "TrainingData/indicators_data/pit"
    files += [x for x in tables.iterdir() if x.is_file() and (
        x.suffix == ".parquet" or x.name.endswith("_pit.csv") or x.name == "security_master.csv"
    )]
    files += list((root / "TrainingData/pit/overrides").glob("*.csv"))
    files += list((root / "TrainingData/pit").glob("*.py"))
    files += list(root.glob("research/*_results.json")) + list(root.glob("research/trials_2026-11-19/*/*.json"))
    manifest = {
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "files_sha256": {str(x.relative_to(root)): breadth.sha256(x) for x in sorted(set(files))},
        "trial_count": 49, "prior_trial_sharpe_variance": float(np.var(pool, ddof=1)),
        "common_names": {"min": min(counts), "max": max(counts)}, "confirmation": "sealed",
    }
    output.mkdir(parents=True)
    (output / "prescore_manifest.json").write_text(json.dumps(manifest, indent=2))
    metrics, returns, artifacts = {}, {}, {}
    stress_panel = replace(panel, spread_est=panel.spread_est * 2)
    for arm in targets:
        base, net = breadth.run_portfolio(panel, p, targets[arm])
        stressed, stress = breadth.run_portfolio(
            stress_panel, replace(p, cost_bps=2, spread_fallback=p.spread_fallback * 2, impact_k=2), targets[arm],
        )
        gross, gross_stats = breadth.run_portfolio(
            panel, replace(p, cost_bps=0, use_spread_cost=False, impact_k=0, sell_fee_table=()), targets[arm],
        )
        trim = remove_top_three(base, dates)
        ic = breadth.rank_ic(pit, panel, ranks[arm])
        metrics[arm] = {
            "net": net, "stress": stress, "gross_zero_cost_rerun": gross_stats,
            "top_three_removed": prior.stats(trim, p.initial_value),
            "rank_ic": float(ic.ic.mean()), "ic_periods": int(ic.ic.notna().sum()),
        }
        returns[arm] = prior.bc.daily_returns(base.equity)
        artifacts[f"{arm}_trades.csv"] = base.trades
        artifacts[f"{arm}_cash_events.csv"] = pd.DataFrame(base.cash_events)
        artifacts[f"{arm}_rank_ic.csv"] = ic
        artifacts[f"{arm}_equity.csv"] = pd.DataFrame({
            "date": dates, "net": base.equity, "cash": base.cash_path, "holdings": base.holdings_path,
            "stressed": stressed.equity, "gross": gross.equity, "top_three_removed": trim,
        })
    diff = breadth.paired_compare(returns["composite"], returns["momentum"])
    all_sharpes = np.concatenate([pool, [arm["net"]["sharpe"] for arm in metrics.values()]])
    if len(all_sharpes) != 49 or not np.isfinite(all_sharpes).all():
        raise ValueError("Invalid final trial pool")
    r = pd.Series(returns["composite"])
    dsr = prior.deflated_sharpe(r.mean() / r.std(ddof=1), all_sharpes / np.sqrt(252), len(r), r.skew(), r.kurt() + 3)
    gates = {
        "paired_effect": diff["difference"] >= 0.20 and diff["lower_one_sided_95"] > 0,
        "deflated_sharpe": dsr["dsr"] >= 0.95,
        **{k: metrics["composite"][k]["sharpe"] > metrics["momentum"][k]["sharpe"]
           for k in ("stress", "top_three_removed")},
    }
    summary = {
        "manifest": manifest, "arms": metrics, "paired_sharpe": diff, "deflated_sharpe": dsr,
        "gates": gates, "advance": all(gates.values()),
        "spy_total_return": prior.stats(prior.spy_tr_equity(pit, dates, p.initial_value), p.initial_value),
    }
    pending = output / "results.json.tmp"
    pending.write_text(json.dumps(summary, indent=2))
    for file, table in artifacts.items():
        table.to_csv(output / file, index=False)
    pending.replace(output / "results.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluate", action="store_true", required=True)
    parser.add_argument("--output", type=Path, default=prior.ROOT / "wf_pit/price_ranks")
    evaluate(parser.parse_args().output)
