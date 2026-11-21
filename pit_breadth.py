"""Run the locked 2016–2024 next-open portfolio breadth experiment."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

import pit_evaluate as prior
from pit_model_comparison import remove_top_three, trial_sharpes, verify_ledger


def targets_for(panel, total_returns: pd.DataFrame, params):
    """Return ordered month-end targets and the underlying eligible ranks."""
    dates = pd.DatetimeIndex(panel.dates)
    observed = total_returns.reindex(columns=panel.tickers)
    score = (observed.shift(21) / observed.shift(126) - 1).reindex(dates)
    schedules = {arm: {} for arm in ("five", "broad", "equal_weight")}
    ranks = {}
    for i in range(1, len(dates) - 1):
        if dates[i].month == dates[i + 1].month:
            continue
        r = score.iloc[i].to_numpy()
        eligible = prior.bc._eligible_mask(panel, i - 1, replace(params, use_member_mask=False))
        eligible &= panel.member[i] & np.isfinite(r)
        ranked = sorted(np.flatnonzero(eligible), key=lambda j: (-r[j], panel.tickers[j]))
        ranks[i] = r[ranked], ranked
        count = min(100, (len(ranked) + 4) // 5)
        schedules["five"][i] = {int(j): 0.2 for j in ranked[:5]}
        schedules["broad"][i] = {int(j): 1 / count for j in ranked[:count]}
        schedules["equal_weight"][i] = {int(j): 1 / len(ranked) for j in ranked}
    return schedules, ranks


def rank_ic(pit, panel, ranks):
    dates = pd.DatetimeIndex(panel.dates)
    opens = prior.wide(pit, "adjusted", "AdjOpen")
    total_return = prior.wide(pit, "adjusted", "TrClose")
    closes = prior.wide(pit, "adjusted", "AdjClose")
    values = (opens * total_return / closes).reindex(index=dates, columns=panel.tickers).to_numpy()
    results = []
    for i, end in zip(ranks, list(ranks)[1:]):
        scores, selected = ranks[i]
        outcomes = values[end + 1, selected] / values[i + 1, selected] - 1
        valid = np.isfinite(outcomes)
        if valid.sum() > 1:
            ic = pd.Series(scores[valid]).corr(pd.Series(outcomes[valid]), method="spearman")
            results.append({"date": str(dates[i].date()), "ic": ic, "names": int(valid.sum())})
    return pd.DataFrame(results)


def paired_compare(broad, five):
    bc = prior.bc
    r = np.column_stack([broad, five])
    if len(r) < 20 or not np.isfinite(r).all():
        raise ValueError("Incomplete or invalid paired daily returns")
    rng = np.random.default_rng(20261121)
    n = len(r)
    starts = rng.integers(0, n - 19, size=(5000, (n + 19) // 20))
    indices = (starts[:, :, None] + np.arange(20)).reshape(5000, -1)[:, :n]
    estimates = []
    for start in range(0, len(indices), 100):
        draw = r[indices[start:start + 100]]
        sharpe = np.sqrt(252) * draw.mean(axis=1) / draw.std(axis=1, ddof=1)
        estimates.extend(sharpe[:, 0] - sharpe[:, 1])
    return {
        "difference": bc.sharpe(broad) - bc.sharpe(five),
        "lower_one_sided_95": float(np.quantile(estimates, 0.05)),
        "ci95": np.quantile(estimates, [0.025, 0.975]).tolist(),
    }


def run_portfolio(panel, params, targets):
    bc = prior.bc
    dates = pd.DatetimeIndex(panel.dates)
    result = bc.run_strategy(panel, params, targets=targets)
    verify_ledger(result, dates, params.initial_value)
    np.testing.assert_allclose(result.equity, result.cash_path + result.holdings_path, atol=0.01)
    cash = pd.Series(0.0, index=dates)
    if result.cash_events:
        events = pd.DataFrame(result.cash_events)
        cash = events.groupby("date").cash_change.sum().reindex(dates, fill_value=0.0)
        np.testing.assert_allclose(events.cost.sum(), result.total_costs, atol=0.01)
    np.testing.assert_allclose(params.initial_value + cash.cumsum(), result.cash_path, atol=0.01)
    if (result.cash_path < -1e-8).any() or (result.holdings_path < 0).any():
        raise ValueError("Unlevered cash and holdings do not reconcile")
    metrics = bc.summarize(result, params.initial_value)
    metrics.update({
        "cost_breakdown": result.cost_breakdown, "cap_blocked": result.cap_blocked,
        "cap_shrunk": result.cap_shrunk, "spread_fallbacks": result.spread_fallbacks,
        "cancelled_open_targets": result.cancelled_entries, "deferred_exit_attempts": result.deferred_exits,
        "average_gross_exposure": float(np.mean(result.holdings_path / result.equity)),
        "yearly": {year: prior.segment(result.equity, dates, pd.Timestamp(f"{year-1}-12-31"),
                                      pd.Timestamp(f"{year}-12-31"))["total_return"]
                   for year in sorted(set(dates.year))},
    })
    return result, metrics


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def registered_trial_pool(new):
    head_to_head = prior.ROOT / "wf_pit/model_comparison/evaluation/results.json"
    data = json.loads(head_to_head.read_text())
    if data["trial_count"] != 45 or data["confirmation"] != "sealed":
        raise ValueError("The required completed 45-trial development ledger is absent")
    previous_arms = ("lstm", "logistic", "lightgbm", "momentum")
    comparison = [data["portfolios"][arm]["net"]["sharpe"] for arm in previous_arms]
    return trial_sharpes(comparison + list(new))


def evaluate(output: Path):
    bc = prior.bc
    if (output / "prescore_manifest.json").exists() or (output / "results.json").exists():
        raise RuntimeError("The registered breadth study already started in this output directory")
    previous_trials = registered_trial_pool([])
    if len(previous_trials) != 45 or not np.isfinite(previous_trials).all():
        raise ValueError("Invalid 45-trial predecessor ledger")
    pit = prior.pp.load_pit(end=prior.END, strict=True)
    baseline = prior.params(cost_bps=1.0)
    panel = prior.panel_for(pit, None)
    dates = pd.DatetimeIndex(panel.dates)
    schedules, ranks = targets_for(panel, prior.wide(pit, "adjusted", "TrClose"), baseline)
    if not ranks or dates[-1] != pd.Timestamp("2024-12-31"):
        raise ValueError("Missing development sessions or rebalance signals")
    output.mkdir(parents=True, exist_ok=True)
    data_path = prior.ROOT / "TrainingData" / "indicators_data" / "pit"
    prereg = prior.ROOT / "research" / "pit_breadth_preregistration.md"
    sources = [prior.ROOT / p for p in (
        "pit_breadth.py", "backtest_core.py", "pit_panel.py", "pit_evaluate.py",
        "pit_model_comparison.py", "audit_backtest.py",
    )]
    sources.extend((prior.ROOT / "TrainingData/pit").glob("*.py"))
    sources.extend((prior.ROOT / "TrainingData/pit/overrides").glob("*.csv"))
    trials = [prior.ROOT / p for p in (
        "wf_pit/model_comparison/evaluation/results.json",
        "research/pit_nextopen_2026-11-20_results.json",
        "research/audit_2026-11-19_results.json",
        "research/walkforward_2026-11-19_results.json",
        "research/latency_2026-11-20_results.json",
        "research/preclose_2026-11-20_results.json",
    )]
    trials.extend(prior.ROOT.glob("research/trials_2026-11-19/*/*.json"))
    manifest = {
        "preregistration_sha256": sha256(prereg),
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=prior.ROOT, text=True).strip(),
        "git_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=prior.ROOT)),
        "code_and_override_sha256": {str(p.relative_to(prior.ROOT)): sha256(p) for p in sorted(sources)},
        "trial_inputs_sha256": {str(p.relative_to(prior.ROOT)): sha256(p) for p in sorted(trials)},
        "prior_trial_sharpe_variance": float(np.var(previous_trials, ddof=1)),
        "data_sha256": {p.name: sha256(p) for p in sorted(data_path.iterdir())
                        if p.is_file() and (p.suffix == ".parquet" or p.name.endswith("_pit.csv")
                                            or p.name == "security_master.csv")},
        "window": [str(dates[0].date()), str(dates[-1].date())], "trial_count": 47,
        "rebalance_count": len(ranks), "confirmation": "sealed",
    }
    (output / "prescore_manifest.json").write_text(json.dumps(manifest, indent=2))
    # Scale the shared panel's spread only, preserving identical eligibility and marks.
    stress_panel = replace(panel, spread_est=panel.spread_est * 2)
    gross = replace(baseline, cost_bps=0, use_spread_cost=False, impact_k=0, sell_fee_table=())
    stats, paired, outputs = {}, {}, {}
    for arm in ("five", "broad"):
        targets = schedules[arm]
        base, net_metrics = run_portfolio(panel, baseline, targets)
        _, gross_metrics = run_portfolio(panel, gross, targets)
        stressed, stress_metrics = run_portfolio(
            stress_panel, replace(baseline, cost_bps=2, spread_fallback=baseline.spread_fallback * 2, impact_k=2),
            targets,
        )
        trimmed = remove_top_three(base, dates)
        stats[arm] = {
            "net": net_metrics, "gross_zero_cost_rerun": gross_metrics, "stress": stress_metrics,
            "remove_top_three": prior.stats(trimmed, baseline.initial_value),
            "median_target_names": float(np.median([len(w) for w in targets.values()])),
        }
        paired[arm] = bc.daily_returns(base.equity)
        outputs[f"{arm}_trades.csv"] = base.trades
        outputs[f"{arm}_cash_events.csv"] = pd.DataFrame(base.cash_events)
        outputs[f"{arm}_equity.csv"] = pd.DataFrame({
            "date": dates, "net": base.equity, "cash": base.cash_path, "holdings": base.holdings_path,
            "stressed": stressed.equity, "remove_top_three": trimmed,
        })
    _, equal = run_portfolio(panel, replace(gross, participation_cap=None), schedules["equal_weight"])
    ic = rank_ic(pit, panel, ranks)
    diff = paired_compare(paired["broad"], paired["five"])
    pool = np.concatenate([previous_trials, [stats[a]["net"]["sharpe"] for a in ("five", "broad")]])
    if len(pool) != 47 or not np.isfinite(pool).all():
        raise ValueError("Invalid 47-trial ledger")
    r = pd.Series(paired["broad"])
    dsr = prior.deflated_sharpe(r.mean() / r.std(ddof=1), pool / np.sqrt(252), len(r), r.skew(), r.kurt() + 3)
    gates = {
        "paired_effect": diff["difference"] >= 0.20 and diff["lower_one_sided_95"] > 0,
        "deflated_sharpe": dsr["dsr"] >= 0.95,
        "stress": stats["broad"]["stress"]["sharpe"] > stats["five"]["stress"]["sharpe"],
        "remove_top_three": stats["broad"]["remove_top_three"]["sharpe"] > stats["five"]["remove_top_three"]["sharpe"],
    }
    result = {
        "manifest": manifest, "portfolios": stats, "paired_sharpe": diff, "deflated_sharpe": dsr,
        "prior_trial_sharpe_variance": float(np.var(pool[:45], ddof=1)),
        "gates": gates, "advance": all(gates.values()),
        "rank_ic": {"mean": float(ic.ic.mean()), "periods": int(ic.ic.notna().sum())},
        "spy_total_return": prior.stats(prior.spy_tr_equity(pit, dates, baseline.initial_value), baseline.initial_value),
        "equal_weight_eligible": equal,
    }
    pending = output / "results.json.tmp"
    pending.write_text(json.dumps(result, indent=2))
    outputs["rank_ic.csv"] = ic
    for file, table in outputs.items():
        table.to_csv(output / file, index=False)
    pending.replace(output / "results.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluate", action="store_true", required=True)
    parser.add_argument("--output", type=Path, default=prior.ROOT / "wf_pit" / "breadth")
    evaluate(parser.parse_args().output)
