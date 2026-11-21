"""Common portfolio selection and paired inference for the PIT model comparison."""
from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pandas as pd

import pit_evaluate as prior
import pit_walk_forward as pit_wf

MODELS = ("lstm", "logistic", "lightgbm")
KEYS = ["Date", "isin"]
PROBS = [f"Pred_Prob_{h}" for h in prior.HZ]
LABELS = [f"Class_{h}" for h in prior.HZ]
FORECAST_ROOT = pit_wf.OUT / "model_comparison"
FROZEN_FEATURE_HASH = "f67687edae68f01af7cc5f639ac1f9ef153677773409ebd06567a68dc60dfc20"
FROZEN_FILE_HASH = "5a82928639e454c968ef5901002939cdd63e03a7c10163ee201a59cffde75346"


def load_matched_forecasts() -> tuple[pd.DataFrame, dict]:
    """Require identical fitted-model inputs and exactly matching prediction keys."""
    parts, audit = [], {}
    for year in range(2016, 2025):
        locations = {
            "lstm": [(f"lstm/meta/Y{year}_s{s}.json", f"lstm/forecasts/Y{year}_s{s}_test.csv.gz")
                     for s in range(3)],
            **{arm: [(f"{arm}/Y{year}.json", f"{arm}/Y{year}_test.csv.gz")] for arm in MODELS[1:]},
        }
        expected = None
        fold_metadata = []
        merged = None
        for arm, files in locations.items():
            arm_probabilities = []
            for seed_index, (meta_path, prediction_path) in enumerate(files):
                meta = json.loads((FORECAST_ROOT / meta_path).read_text())
                validation_path = prediction_path.replace("_test.csv.gz", "_val.csv.gz")
                fold_metadata.append({
                    **meta,
                    "metadata_sha256": pit_wf.file_sha(FORECAST_ROOT / meta_path),
                    "test_forecast_sha256": pit_wf.file_sha(FORECAST_ROOT / prediction_path),
                    "validation_forecast_sha256": pit_wf.file_sha(FORECAST_ROOT / validation_path),
                })
                if (meta["features_sha256"], meta["features_file_sha256"]) != (
                    FROZEN_FEATURE_HASH, FROZEN_FILE_HASH,
                ):
                    raise ValueError(f"Unregistered feature hashes in {meta_path}")
                if arm == "lightgbm" and [p["random_state"] for p in meta["parameters"]] != [
                    1000 * year + seed for seed in range(3)
                ]:
                    raise ValueError(f"Unregistered LightGBM seeds in {meta_path}")
                if arm == "lstm" and (meta["seed_index"], meta["seed"], meta["corrected_labels"]) != (
                    seed_index, 1000 * year + seed_index, True,
                ):
                    raise ValueError(f"Unregistered LSTM seed or labels in {meta_path}")
                signature = tuple(meta[key] for key in (
                    "sample_digests", "feature_indices", "n_train", "n_val",
                    "features_sha256", "features_file_sha256", "shared_code_sha256",
                ))
                sources = meta["provenance"]["source_hashes"].copy()
                sources.pop("pit_model_tabular.py", None)
                signature += (sources, meta["provenance"]["git_commit"])
                if expected is None:
                    expected = signature
                    audit[year] = dict(meta)
                if arm == "logistic":
                    audit[year]["train_pos_rate"] = meta["train_pos_rate"]
                if signature != expected:
                    raise ValueError(f"Sample or input mismatch for {meta_path}")
                data = pd.read_csv(
                    FORECAST_ROOT / prediction_path, parse_dates=["Date"],
                    usecols=KEYS + PROBS + LABELS,
                ).set_index(KEYS, verify_integrity=True).sort_index()
                if not (data.index.get_level_values("Date").year == year).all():
                    raise ValueError(f"Wrong test year in {prediction_path}")
                if merged is None:
                    merged = data[LABELS].copy()
                if not merged[LABELS].equals(data[LABELS]):
                    raise ValueError(f"Prediction keys or labels differ in {prediction_path}")
                raw = data[PROBS].to_numpy()
                if not np.isfinite(raw).all() or ((raw < 0) | (raw > 1)).any():
                    raise ValueError(f"Invalid probability in {prediction_path}")
                arm_probabilities.append(raw)
            merged[[f"{arm}_{col}" for col in PROBS]] = np.mean(arm_probabilities, axis=0)
        audit[year] = {**audit[year], "fits": fold_metadata}
        parts.append(merged.reset_index())
    return pd.concat(parts, ignore_index=True), audit


def forecast_quality(matched: pd.DataFrame, audit: dict) -> tuple[dict, pd.DataFrame]:
    """Summarize common labeled rows and retain daily paired forecast metrics."""
    summary, daily = {}, []
    for j, horizon in enumerate(prior.HZ):
        label = f"Class_{horizon}"
        subset = matched.dropna(subset=[label])
        y = subset[label]
        base = subset.Date.dt.year.map({yr: meta["train_pos_rate"][j] for yr, meta in audit.items()})
        baseline_error = (base - y).pow(2).mean()
        summary[horizon] = {"rows": len(subset), "excluded": len(matched) - len(subset), "models": {}}
        by_date = subset.groupby("Date", sort=True)
        label_rank = by_date[label].rank()
        for arm in MODELS:
            probability = subset[f"{arm}_Pred_Prob_{horizon}"]
            clipped = probability.clip(1e-6, 1 - 1e-6)
            brier = (probability - y).pow(2)
            loss = -(y * np.log(clipped) + (1 - y) * np.log1p(-clipped))
            rank = probability.groupby(subset.Date).rank()
            ranks = pd.DataFrame({"Date": subset.Date, "label": label_rank, "prob": rank})
            covariances = ranks.groupby("Date")[["label", "prob"]].corr()
            ic = covariances.xs("label", level=1)["prob"]
            bins = pd.cut(probability, np.linspace(0, 1, 11), include_lowest=True, labels=False)
            reliability = pd.DataFrame({"bin": bins, "event": y, "probability": probability})
            reliability = reliability.groupby("bin").agg(
                rows=("event", "size"), event_rate=("event", "mean"), mean_probability=("probability", "mean"),
            ).reset_index()
            summary[horizon]["models"][arm] = {
                "ic": float(ic.mean()), "ic_dates": int(ic.count()),
                "skipped_ic_dates": int(matched.Date.nunique() - ic.count()),
                "brier": float(brier.mean()), "log_loss": float(loss.mean()),
                "brier_skill": float(1 - brier.mean() / baseline_error),
                "reliability": reliability.to_dict("records"),
            }
            daily.append(pd.DataFrame({
                "ic": ic, "brier": brier.groupby(subset.Date).mean(),
                "log_loss": loss.groupby(subset.Date).mean(),
            }).assign(arm=arm, horizon=horizon).reset_index())
    return summary, pd.concat(daily, ignore_index=True)


def verify_outcome_dates(pit, matched):
    from pit_model_label_dates import realization_dates

    end = pd.Timestamp(pit_wf.END)
    for isin, rows in matched.groupby("isin", sort=False):
        bars = pit.adjusted[isin]
        ends = realization_dates(bars.index[bars.AdjClose.notna()], rows.Date)
        present = rows[LABELS].notna()
        present.columns = prior.HZ
        if (present & ~ends.le(end)).any(axis=None):
            raise ValueError(f"An outcome falls outside the registered development period: {isin}")


def verify_forecast_coverage(matched):
    path = pit_wf.OUT / "features.parquet"
    if pit_wf.file_sha(path) != FROZEN_FILE_HASH:
        raise ValueError("Frozen input file no longer matches the registration")
    source = pd.read_parquet(path, columns=KEYS + ["member"])
    ready = source.groupby("isin", sort=False).cumcount() >= pit_wf.WINDOW
    development = source.Date.between(prior.START, pit_wf.END)
    expected_keys = source.loc[ready & development & source.member, KEYS]
    observed_keys = matched[KEYS]
    for keys in (expected_keys, observed_keys):
        dates = keys["Date"]
        if keys.isna().any(axis=None) or dates.dt.tz is not None or not dates.eq(dates.dt.normalize()).all():
            raise ValueError("Forecast coverage keys require nonmissing, timezone-naive session dates")
    expected = pd.MultiIndex.from_frame(expected_keys)
    observed = pd.MultiIndex.from_frame(observed_keys)
    if not expected.is_unique or not observed.is_unique:
        raise ValueError("Duplicate test forecast keys")
    if len(expected) != len(observed) or not observed.difference(expected).empty:
        raise ValueError("Forecast coverage does not match the registered development eligibility")


def forecast_comparisons(daily: pd.DataFrame) -> dict:
    """Compare equal-horizon daily metrics with shared resampled exchange dates."""
    rng = np.random.default_rng(20261121)
    aligned = daily.pivot(index="Date", columns=["arm", "horizon"], values=["ic", "brier", "log_loss"])
    n = len(aligned)
    block = 126
    if n < block:
        raise ValueError("Insufficient dates for forecast comparisons")
    blocks = rng.integers(0, n - block + 1, size=(5000, (n + block - 1) // block))
    indices = (blocks[:, :, None] + np.arange(block)).reshape(5000, -1)[:, :n]
    comparisons = {}
    for metric in ("ic", "brier", "log_loss"):
        comparisons[metric] = {}
        for arm in MODELS[1:]:
            delta = aligned[metric]["lstm"] - aligned[metric][arm]
            values = delta.to_numpy()
            estimates = [np.nanmean(np.nanmean(values[indices[i:i + 100]], axis=1), axis=1)
                         for i in range(0, 5000, 100)]
            comparisons[metric][arm] = {
                "lstm_minus_baseline": float(delta.mean().mean()),
                "ci95": np.nanquantile(np.concatenate(estimates), [0.025, 0.975]).tolist(),
            }
    return comparisons


def ranked_offers(probabilities: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Encode the top decile and each selected stock's winning horizon for the engine."""
    horizons = list(prior.HZ)
    if horizons != list(pit_wf.HORIZONS):
        raise ValueError("Horizon tie-breaking requires shortest to longest order")
    columns = [f"Pred_Prob_{horizon}" for horizon in horizons]
    scores = probabilities[columns]
    best = scores.max(axis=1)
    valid = probabilities.loc[best.notna(), ["Date", "isin"]].copy()
    valid["score"] = best.loc[valid.index]
    valid["horizon"] = scores.loc[valid.index].idxmax(axis=1)
    valid = valid.sort_values(["Date", "score", "isin"], ascending=[True, False, True])
    by_date = valid.groupby("Date", sort=False)
    rank = by_date.cumcount()
    universe = by_date["isin"].transform("size")
    valid["priority"] = 1.0 - rank / universe
    selected = valid.loc[rank < (universe + 9) // 10].copy()
    for horizon, column in zip(horizons, columns):
        selected[column] = selected.priority.where(selected.horizon.eq(column))
        selected[f"Pred_Prob_Std_{horizon}"] = 0.0
    return prior.to_scores(selected)


def paired_sharpes(returns: pd.DataFrame, reference: str = "lstm") -> dict:
    """Use the same moving blocks for every comparison against the LSTM."""
    if returns.isna().any(axis=None) or len(returns) < 20:
        raise ValueError("Paired inference requires complete, aligned returns")
    rng = np.random.default_rng(20261121)
    returns = returns[[reference, *[col for col in returns if col != reference]]]
    values = returns.to_numpy()
    block = 20
    draws = 5000
    n = len(values)
    starts = rng.integers(0, n - block + 1, size=(draws, (n + block - 1) // block))
    indices = (starts[:, :, None] + np.arange(block)).reshape(draws, -1)[:, :n]
    annual = np.sqrt(252)
    sample = np.array([prior.bc.sharpe(values[:, i]) for i in range(values.shape[1])])
    simulated = np.empty((draws, values.shape[1]), dtype=float)
    for start in range(0, draws, 100):
        batches = values[indices[start:start + 100]]
        stdev = batches.std(axis=1, ddof=1)
        mean = batches.mean(axis=1)
        simulated[start:start + 100] = np.divide(
            annual * mean, stdev, out=np.full_like(mean, np.nan), where=stdev > 0,
        )
    result = {}
    for i, name in enumerate(returns.columns[1:], start=1):
        diff = simulated[:, 0] - simulated[:, i]
        if not np.isfinite(diff).all() or not np.isfinite(sample[[0, i]]).all():
            raise ValueError(f"Undefined paired Sharpe against {name}")
        result[name] = {
            "difference": float(sample[0] - sample[i]),
            "ci95": np.quantile(diff, [0.025, 0.975]).tolist(),
            "adjusted_lower": float(np.quantile(diff, 0.05 / (values.shape[1] - 1))),
        }
    return result


def portfolio_inputs(pit, matched, params):
    bc = prior.bc
    eligibility = prior.panel_for(pit, {})
    allowed = pd.DataFrame(
        np.stack([bc._eligible_mask(eligibility, i, params) for i in range(len(eligibility.dates))]),
        index=eligibility.dates, columns=eligibility.tickers,
    ).stack()
    momentum = prior.wide(pit, "adjusted", "TrClose")
    momentum = (momentum.shift(21) / momentum.shift(126) - 1).stack()
    keys = pd.MultiIndex.from_frame(matched[KEYS])
    values = momentum.reindex(keys).to_numpy()
    engine_ok = allowed.reindex(keys, fill_value=False).to_numpy()
    date_positions = pd.DatetimeIndex(eligibility.dates).get_indexer(matched.Date)
    stock_positions = pd.Index(eligibility.tickers).get_indexer(matched["isin"])
    mapped = (date_positions >= 0) & (stock_positions >= 0)
    member = np.zeros(len(matched), dtype=bool)
    close = np.full(len(matched), np.nan)
    member[mapped] = eligibility.member[date_positions[mapped], stock_positions[mapped]]
    close[mapped] = eligibility.close[date_positions[mapped], stock_positions[mapped]]
    price_ok = np.isfinite(close) & (close >= params.min_price)
    valid = engine_ok & np.isfinite(values)
    exclusions = pd.DataFrame({
        "year": matched.Date.dt.year, "matched_forecasts": 1, "eligible": valid.astype(int),
        "missing_listing_panel": (~mapped).astype(int),
        "not_member": (mapped & ~member).astype(int),
        "missing_or_below_price_floor": (member & ~price_ok).astype(int),
        "causal_spike_filter": (member & price_ok & ~engine_ok).astype(int),
        "eligible_without_observed_momentum": (engine_ok & ~np.isfinite(values)).astype(int),
    }).groupby("year").sum()
    if (exclusions.eligible == 0).any():
        raise ValueError("A development fold has no eligible common trading rows")
    common = matched.loc[valid].copy()
    offers = {}
    for arm in MODELS:
        scores = common[KEYS + [f"{arm}_{col}" for col in PROBS]].copy()
        scores.columns = KEYS + PROBS
        offers[arm] = ranked_offers(scores)
    scores = common[KEYS].assign(**dict.fromkeys(PROBS, np.nan))
    scores["Pred_Prob_1m"] = values[valid]
    offers["momentum"] = ranked_offers(scores)
    return offers, exclusions.to_dict("index")


def remove_top_three(result, dates):
    equity = result.equity.copy()
    if not result.trades.empty:
        winners = result.trades.loc[result.trades["PnL$"] > 0].nlargest(3, "PnL$")
        for _, trade in winners.iterrows():
            equity[dates >= trade["SellDate"]] -= trade["PnL$"]
    return equity


def verify_ledger(result, dates, initial_value):
    if len(result.equity) != len(dates) or not np.isfinite(result.equity).all():
        raise ValueError("Equity values must be finite and match the panel calendar")
    if (result.equity <= 0).any():
        raise ValueError("Nonpositive equity prevents aligned daily-return inference")
    if not np.isclose(sum(result.cost_breakdown.values()), result.total_costs):
        raise ValueError("Trading cost components do not reconcile")
    if result.trades.empty:
        return
    trades = result.trades
    if not (trades.SignalDate.lt(trades.BuyDate) & trades.BuyDate.le(trades.SellDate)).all():
        raise ValueError("Trade ledger contains a fill with inconsistent dates")
    if not result.open_at_end and not np.isclose(
        result.equity[-1], initial_value + trades["PnL$"].sum(), atol=0.01, rtol=0,
    ):
        raise ValueError("Closed-position equity does not reconcile to realized P&L")


def trial_sharpes(new_values):
    previous = json.loads((prior.ROOT / "research/pit_nextopen_2026-11-20_results.json").read_text())
    arms = [previous[f"arm_{arm}"]["summary"]["sharpe"] for arm in "FA"]
    comparators = [previous["comparators"][name]["sharpe"] for name in ("MOM12-1", "MOM6-1", "REV1M")]
    earlier = prior.trial_pool(arms + comparators)
    timing = previous["arm_F"]["secondary"]["timing_next_close"]["sharpe"]
    return np.concatenate([earlier, [timing], new_values])


def evaluate() -> None:
    bc = prior.bc
    output = FORECAST_ROOT / "evaluation"
    if (output / "results.json").exists():
        raise RuntimeError("The registered development evaluation already exists")
    matched, audit = load_matched_forecasts()
    verify_forecast_coverage(matched)
    pit = prior.pp.load_pit(end=pit_wf.END, strict=True)
    verify_outcome_dates(pit, matched)
    params = prior.params(min_accepted=0.0, std_factor=0.0)
    offers, coverage = portfolio_inputs(pit, matched, params)
    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "provenance": audit, "trading_coverage_by_year": coverage,
        "arms": list(offers), "prior_trials": 41, "registered_trials": 45,
        "development_window": [prior.START, pit_wf.END], "fill": params.fill_mode,
        "stress_spread_multiplier": 2, "stress_impact_coefficient": 2,
        "confirmation": "sealed",
    }
    (output / "prescore_manifest.json").write_text(json.dumps(manifest, indent=2))
    quality, forecast_daily = forecast_quality(matched, audit)
    metrics, base_returns, ledgers = {}, {}, {}
    dates = None
    for arm, scores in offers.items():
        panel = prior.panel_for(pit, scores)
        panel_dates = pd.DatetimeIndex(panel.dates)
        if dates is not None and not dates.equals(panel_dates):
            raise ValueError("Portfolio calendars differ")
        dates = panel_dates
        base = bc.run_strategy(panel, params)
        gross = bc.run_strategy(panel, replace(params, use_spread_cost=False, impact_k=0, sell_fee_table=()))
        stress = bc.run_strategy(prior.panel_for(pit, scores, spread_mult=2), replace(params, impact_k=2))
        for portfolio in (base, gross, stress):
            verify_ledger(portfolio, dates, params.initial_value)
        pruned = remove_top_three(base, dates)
        metrics[arm] = {
            "net": bc.summarize(base, params.initial_value),
            "gross_zero_cost_rerun": bc.summarize(gross, params.initial_value),
            "stress": bc.summarize(stress, params.initial_value),
            "remove_top_three": prior.stats(pruned, params.initial_value),
            "cost_breakdown": base.cost_breakdown, "cap_blocked": base.cap_blocked,
            "cap_shrunk": base.cap_shrunk, "spread_fallbacks": base.spread_fallbacks,
        }
        base_returns[arm] = bc.daily_returns(base.equity)
        ledgers[arm] = (base.trades, pd.DataFrame({
            "Date": dates, "net": base.equity, "gross_zero_cost_rerun": gross.equity,
            "stress": stress.equity, "remove_top_three": pruned,
        }))
    differences = paired_sharpes(pd.DataFrame(base_returns, index=dates[1:]))
    pool = trial_sharpes([metrics[arm]["net"]["sharpe"] for arm in offers])
    if len(pool) != 45 or not np.isfinite(pool).all():
        raise ValueError("Trial accounting does not match the registered 45 finite Sharpes")
    r = pd.Series(base_returns["lstm"])
    dsr = prior.deflated_sharpe(
        float(r.mean() / r.std(ddof=1)), pool / np.sqrt(252), len(r),
        float(r.skew()), float(r.kurt() + 3),
    )
    gate = {
        "paired_effects": all(d["difference"] >= 0.20 and d["adjusted_lower"] > 0
                              for d in differences.values()),
        "deflated_sharpe": bool(dsr["dsr"] >= 0.95),
        "stress": all(metrics["lstm"]["stress"]["sharpe"] > metrics[arm]["stress"]["sharpe"]
                      for arm in differences),
        "remove_top_three": all(
            metrics["lstm"]["remove_top_three"]["sharpe"] > metrics[arm]["remove_top_three"]["sharpe"]
            for arm in differences
        ),
    }
    result = {
        "provenance": audit, "trading_coverage_by_year": coverage, "trial_count": 45,
        "forecasts": quality, "forecast_comparisons": forecast_comparisons(forecast_daily),
        "forecast_equal_horizon": {
            arm: {metric: float(np.mean([quality[h]["models"][arm][metric] for h in prior.HZ]))
                  for metric in ("ic", "brier", "log_loss", "brier_skill")}
            for arm in MODELS
        },
        "forecast_daily_means_by_year": forecast_daily.assign(year=forecast_daily.Date.dt.year)
        .groupby(["arm", "horizon", "year"])[["ic", "brier", "log_loss"]].mean().reset_index().to_dict("records"),
        "portfolios": metrics, "lstm_minus_baselines": differences,
        "historical_uncertainty_adjusted_reference": json.loads(
            (prior.ROOT / "research/pit_nextopen_2026-11-20_results.json").read_text()
        )["arm_F"]["summary"],
        "spy_total_return": prior.stats(prior.spy_tr_equity(pit, dates, params.initial_value), params.initial_value),
        "deflated_sharpe": dsr, "gate": gate, "advance": all(gate.values()),
        "confirmation": "sealed",
    }
    serialized = json.dumps(result, indent=2)
    output.mkdir(parents=True, exist_ok=True)
    forecast_daily.to_csv(output / "forecast_daily.csv.gz", index=False)
    for arm, (trades, equity) in ledgers.items():
        trades.to_csv(output / f"{arm}_trades.csv", index=False)
        equity.to_csv(output / f"{arm}_equity.csv", index=False)
    pending = output / "results.json.tmp"
    pending.write_text(serialized)
    pending.replace(output / "results.json")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluate", action="store_true", required=True)
    parser.parse_args()
    evaluate()
