# Old LSTM rule on 2025-01-02 → 2026-11-18 (owner-unsealed, descriptive)

Written 2026-11-23, before any 2025 or 2026 forecast, trade or return of this recipe was produced or read.

## Decision record

- On 2026-11-23 the project owner explicitly chose to unseal the reserved confirmation window (2025-01-02 → 2025-11-18) after being told that it is the last untouched data and that the recipe failed its 2016–2024 promotion gate (restored rule DSR 0.348 at 50 trials; matched study DSR 0.069 at 56 trials).
- This is **not** a confirmation run. The preregistered confirmation was reserved for a recipe that passed every development gate; none did. Whatever the outcome, the result is descriptive and cannot promote the strategy. After this run no untouched pre-2026-11-19 data remains for any future confirmation.
- 2025-11-19 → 2026-11-18 was previously used by the pre-close study (different strategy). It is included here as already-seen data.
- Trial count: this adds one scored strategy arm (the restored rule) → **N = 57**. The raw top-decile control is a replay of a logged rule on new dates and is reported for context only.

## Frozen recipe (no changes, no tuning)

- Features: the 34 frozen OHLCV + SPY features (`pit_walk_forward.FEATURES`, features sha `f67687ed…`), recomputed with the unchanged `security_features` / `spy_features` code on PIT data loaded to 2026-11-18. **Parity check:** every feature value dated ≤ 2024-12-31 must match the frozen `wf_pit/features.parquet` (float32, abs tol 1e-5); otherwise stop and report.
- Folds: `walk_forward.fold_dates` for test years 2025 and 2026 (validation = 252 sessions ending 126 sessions before the test year; 126-session purge). Corrected labels via `pit_model_label_dates.model_fold` (the `--comparison` path used by the restored-rule forecasts). Test labels are truncated at 2026-11-18 and are not used for trading.
- Model: unchanged `walk_forward.build_model`, training loop, early stopping and 25-pass MC dropout of `pit_walk_forward.run_job`. Seeds `1000·year + k`, k = 0, 1, 2. No hyperparameter or architecture change.
- Pooling: `pit_evaluate.ensemble` (law of total variance) across the 3 seeds per fold, exactly as `pit_lstm_rule_attribution.corrected_forecasts`.
- Eligibility: the head-to-head common trading rows (engine eligibility mask and an observed 6-1 momentum value), as in `pit_model_comparison.portfolio_inputs`.
- **Restored rule:** best horizon of pooled p − σ, offer only if strictly > 0.25; five slots; `StrategyParams.pit()` defaults (next-open fills, spread + square-root impact k = 1.0, SEC/FINRA fees from the dated table, 5% ADV cap, splits, dividends, delisting settlement); 1,000,000 USD start on 2025-01-02, cash; marked through 2026-11-18.
- **Control (context):** raw-probability top-decile offers (`ranked_offers`), σ ignored, same engine.
- **Benchmark:** SPY total return over the same sessions.

## What will be reported (computed once)

1. Restored rule, control and SPY TR: total return, CAGR, annualized Sharpe, max drawdown, for the full window and separately for 2025 (to 2025-12-31) and 2026 YTD (to 2026-11-18); also the original sealed sub-window 2025-01-02 → 2025-11-18.
2. Restored minus SPY and restored minus control: paired annualized Sharpe difference with 5,000 shared 20-session moving-block draws, seed 20261123, one-sided 95% lower bound.
3. Cost stress (spread ×2, impact k = 2) and removal of the three largest winners.
4. Trades, time in market, horizon mix, top-3 share of net P&L, per-seed fold AUC on realized test labels.
5. Deflated Sharpe of the restored rule's out-of-sample returns at N = 57 using the registered trial Sharpe pool plus this arm.

**Fixed reading rule (descriptive only):** the out-of-sample period is called *consistent with the development result* if the restored rule's net Sharpe exceeds SPY TR's and the paired lower bound vs SPY is above zero. Otherwise it is *not consistent*. With under two years of data the lower bound is expected to be wide; neither reading promotes the strategy or justifies live capital.

No other variant (cutoff, slots, seeds, horizons, costs) will be run on this window. Any later change is a new trial on seen data.
