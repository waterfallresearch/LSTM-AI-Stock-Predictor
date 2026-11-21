# PIT S&P 500 next-open study: preregistration (2026-11-20)

Written **before** any model is trained or any strategy is run on the point-in-time data. Results go in
`pit_nextopen_2026-11-20_results.md` / `.json`. Any change after results are seen is logged below as an amendment and
counted as a new trial.

## Question
On a survivorship-free S&P 500 universe, does the walk-forward LSTM ranking earn risk-adjusted returns:
- above SPY total return,
- above shuffled signals,
- above simple momentum and reversal rankings run under identical rules,

after next-open fills and a realistic cost model?

- **H0:** no information beyond what the simple rankings or chance explain.
- **H1:** the LSTM ranking adds value out of sample across years.
- **Prior:** low. The old-data walk-forward failed the deflated Sharpe test (DSR 0.39 at N = 30). The latency study
  (`latency_2026-11-20_results.md`) found the signal behaves partly like short-term reversal.

## Preconditions (nothing below runs until all hold)
1. **Data layer accepted.** `research/pit_data_2026-11-19_acceptance.md` records a verdict of ACCEPTED under its own rule,
   with P2 handled only through its logged amendment (P2a, consolidated close match). If any test still fails, the
   affected securities and sessions are excluded with a documented reason, and exclusions above 0.5% of member-sessions
   block this study.
2. **Panel adapter tested.** A new `pit_panel.py` turns the `TrainingData/indicators_data/pit/` artifacts into
   `backtest_core.build_panel` inputs. It is unit-tested on known securities before any strategy run:
   - one split, one cash dividend, one cash merger, one stock merger, one spin-off, and one index deletion that stays
     listed.
   - The adapter's tests are written and passing before the first fold is trained.
3. **Feature list frozen.** The LSTM feature list (see Design) is frozen in code before the first fold is trained, and
   its sha256 is recorded in the results.

## Data (frozen)
- **Universe:** securities keyed by ISIN, XNYS sessions.
  - **Entry eligibility:** a security may be *entered* only on sessions where it is a member (`membership_pit.csv`; panel
    column `Member`, `use_member_mask=True`).
  - **Holding through removal:** a position opened while a member is held to its normal exit even after it leaves the
    index (it remains tradable), unless a settlement closes it first.
- **Execution prices:** RAW (unadjusted) open/high/low/close from `prices_pit.parquet`. Only bars with `valid_bar = True`
  are used; others are NaN.
- **Signal and feature prices:** split- and total-return-adjusted series built from `adjustment_factors_pit.parquet`
  (`split_factor`, `tr_factor`). Every feature for session t uses only bars at or before t.
- **Volume:** `volume_consolidated` from `consolidated_pit.parquet`, never the venue volume (P2 amendment).
- **Spreads:** `spread_est` from `spreads_pit.parquet` (21-session trailing estimate, dated when known). Missing values
  use the engine's 0.2% fallback; the fallback count is reported.
- **Corporate actions, using engine inputs:**
  - **Splits and consolidations:** `corporate_actions_pit.csv` rows with a verified status, at their `trading_session`,
    factor = new shares per old share.
  - **Cash dividends:** `dividends_pit.csv` (USD rows only; flagged rows excluded and counted).
  - **Spin-offs and other distributions in kind:** credited as a cash dividend on the ex-session. The value per share
    equals the value removed from the parent, derived from the `tr_factor` step on that session (net of any same-day
    cash dividend). This preserves the holder's value as the total-return series does. It is unit-tested on at least
    three verified demergers.
  - **Terminal events:** `settlement_pit.csv`, using `settlement_value_used` as the cash and stock legs, the successor
    open from the file, and `outcome`. OTC failures settle at their documented value. A settlement whose successor is not
    in the panel is converted to its documented cash value.
    - **Settlement date:** the first XNYS session after `last_bar`. A stock leg is valued at the successor's open on
      `successor_open_date`, so the engine waits for it.
- **Benchmark:** SPY total return (`spy_pit.csv` `tr_index`). Also the equal-weight member universe (daily rebalanced,
  total return, no costs, which flatters the comparator).
- **Reserved period:** nothing on or after 2025-01-02 is read, except in the single confirmation run defined below.

## Design (frozen)
- **Test years:** 2016-2024 (9 folds). There is one continuous backtest from the first session of 2016 to 2024-12-31,
  and each day uses the model trained before that year.
- **Fold windows:** identical to `walkforward_2026-11-19_preregistration.md`.
  - test = year Y;
  - validation = the 252 sessions ending 126 sessions before Y;
  - training ends 126 sessions before validation (purge and embargo for the longest label);
  - training starts at the first session of 2011 with a full 61-bar window.
- **Training rows:** member-sessions only. A row is dropped if its label window runs past the security's last valid bar;
  the number dropped is reported.
- **Labels and thresholds:** forward log return of the adjusted close over 1d / 1w / 1m / 6m. The per-stock label
  threshold is the mean + 1σ of that stock's training-window returns (same rule as before).
- **Features:** the per-stock technical features that `TrainingData/processor.py` derives from OHLCV only:
  - returns, moving averages, EMA, RSI, MACD, Bollinger, volatility, z-score, momentum, overnight gap, abnormal
    volume, intraday range;
  - all computed on adjusted PIT bars with consolidated volume;
  - plus SPY return and volatility features from `spy_pit.csv`.
  - No alternative data (insider, congressional, sentiment, options) and no VIX (not entitled).
  - The scaler and the constant-feature drop list are fit on training rows only.
- **Model and training:** identical to the old walk-forward:
  - architecture Conv1D 32 → BN → MCDropout 0.3 → LSTM 64 → MCDropout 0.3 → Dense 32 → Dense 4 sigmoid;
  - Adam, BCE, batch 128, at most 100 epochs, early stopping on validation;
  - 3 seeds per fold (seed = 1000·Y + k), TF determinism on.
  - **Primary signal:** the seed ensemble, p = mean of seed means, σ = sqrt(mean within-seed variance + variance across
    seed means).

## Strategy and execution (frozen)
- **Rules:** adj = p − 1.0·σ; enter if adj > 0.25; best horizon per security; 5 equal-weight slots; no new signals on the
  final session.
- **Engine:** `backtest_core.py` with `StrategyParams.pit(...)`.
  - **Fills:** `fill="next_open"`. Entries happen at the open after the signal; time exits happen at the open; exits are
    deferred through halts.
  - **Universe:** `use_member_mask=True`.
  - **Costs:**
    - `cost_bps=0` (no flat cost);
    - half of `spread_est` per fill;
    - square-root impact with `impact_k=1.0` (a placeholder fixed here, not tuned);
    - SEC Section 31 + FINRA TAF on sells from `TrainingData/pit/overrides/fee_rates.csv` (`bc.load_sell_fee_table()`);
    - participation cap of 5% of ADV20 (consolidated).
  - **Price floor:** $5 minimum raw close on the signal day. Causal 80% spike filter on raw closes with split
    factors applied (the engine's split-aware move), so splits never trigger it.
  - **Starting capital:** $1,000,000, so that impact and the cap are realistic for S&P names. The old $5,000 made them
    negligible. This changes cost scale only, not the selection rules.

## Comparators (same engine, same window, same costs and rules wherever they trade)
1. **MOM12-1:** cross-sectional percentile rank, among members, of the adjusted return from t−252 to t−21. The score is
   placed in the 1m horizon and the others are blank; σ = 0; threshold 0.80 (top quintile); 5 slots.
2. **MOM6-1:** same, with the return from t−126 to t−21.
3. **REV1M:** same, with −(return from t−21 to t), the short-term reversal.
4. **SPY total return**, and the equal-weight member universe.
5. **Shuffle control:** 500 within-day permutations of (p, σ) across that day's member securities, same rules.

## Trial accounting
- The cumulative count before this study is N = 31.
- This study executes 4 new configurations: LSTM primary, MOM12-1, MOM6-1, REV1M. N becomes **35**, and the deflated
  Sharpe uses N = 35.
- No threshold, horizon, cost or feature choice is tuned on 2016-2024. Any later variant is a new trial.

## Primary tests (LSTM ensemble, frozen strategy, 2016-2024)

| # | Test | Passes if |
|---|---|---|
| 1 | CAGR vs SPY total return | strategy CAGR > SPY TR CAGR |
| 2 | Shuffle control, 500 permutations | one-sided p (total return) ≤ 0.05 |
| 3 | 20-session block bootstrap, 5,000 resamples | Sharpe 95% CI excludes 0 |
| 4 | Deflated Sharpe, N = 35 | DSR ≥ 0.95 |
| 5 | vs best simple ranking | the LSTM's daily-return Sharpe exceeds the best of MOM12-1 / MOM6-1 / REV1M; a paired 20-session block bootstrap 95% CI of the Sharpe difference excludes 0 |

## Secondary reporting (informational, not pass/fail)
- **Stability:** year-by-year returns vs SPY TR; single-seed Sharpes.
- **Robustness:** cost stress with 2× spread and impact_k = 2; removing the top 3 trades.
- **Cost and capacity:** turnover, cost breakdown (spread / impact / fees), spread-fallback count, and entries shrunk or
  blocked by the cap.
- **Timing:** the same LSTM run with `fill="next_close"`, as a timing diagnostic only (it counts as a trial, so N = 36 for
  any later study).
- **Portfolio exposures:** sector and market beta of holdings.

## Verdict rule
- **Edge supported:** tests 1-5 all pass.
- **Ranking informative but not distinct from simple factors:** tests 1-4 pass but 5 fails.
- **Edge not supported:** any of tests 1-4 fails.

## Confirmation run (only if "Edge supported")
Run exactly once, with `confirm=True`, on 2025-01-02 → 2025-11-18 (shortened by amendment 3):
- one model per seed trained with the same fold rule, so the test year is 2025 and training/validation end before it;
- the frozen strategy, unchanged.

It passes if, over the full confirmation window:
- the strategy's total return exceeds SPY total return, and
- its Sharpe is above 0.

Its result is reported whatever it is, and the confirmation period is then considered used.

## Amendment log (all made before any model was trained or any strategy run; no trial added)
- **2026-11-20, amendment 1: spread source.** The data layer found that the daily-bar spread estimator overstates
  S&P 500 spreads by about 10x:
  - estimator `spread_est`: about 27 bp;
  - consolidated closing quoted spread: median 2.5 bp over member-sessions 2011-2024.

  **New rule:** `SpreadEst` = the trailing 21-session median (at least 10 observations) of the consolidated closing
  quoted spread (`consolidated_pit.parquet` `quoted_spread`), dated at the close it was observed. Where that is
  missing, use `spread_est`, which is conservative, then the engine's 0.2% fallback. The engine charges half of the
  previous session's value per fill. Implemented in `pit_panel.load_pit`.
- **2026-11-20, amendment 2: new precondition, complete consolidated data.**
  - The current build has no consolidated volume or quotes at all for **102 of the securities that are ever members**,
    mostly non-US-domiciled ISINs (for example NCLH, GRMN, ALLE, PRGO) and some delisted names. That is about 7.2% of
    member-sessions.
  - Under the ADV participation cap these securities could never be entered, which would silently re-introduce
    selection bias.
  - `pit_panel.load_pit(strict=True)` (the default) therefore refuses to load until the data layer maps them. No study
    run may use `strict=False`.
- **2026-11-20, amendment 3: confirmation window and trial count (user decision).**
  - The user chose to spend 2025-11-19 → 2026-11-18, the only LSEG intraday history, on the pre-close test
    (`preclose_2026-11-20_preregistration.md`).
  - The confirmation run below therefore covers **2025-01-02 → 2025-11-18** only. The later year is recorded as used.
  - The pre-close study adds 4 trials before this study runs, so this study's deflated Sharpe uses **N = 39**,
    not 35.
- **2026-11-20, amendment 4: volume fallback and the strict rule.**
  - The data layer mapped 93 of the then-115 missing securities to LSEG `XYZ.K` consolidated RICs. 22 remain without
    any consolidated series, mostly failed or bankrupt names (SIVB, FRC, SBNY, BBBY, ...). Dropping them would bring
    back survivorship bias.
  - **Volume** is now `consolidated_pit.parquet` `volume_adv`: consolidated volume where it exists, otherwise venue
    volume scaled by the trailing 63-session median consolidated/venue ratio of other securities on the same venue
    (causal). Out of sample, its ADV21 median absolute error is 12%, with 78% of cases within ±25%.
  - **Quotes:** securities on that `venue_scaled` fallback have no quotes, so they use `spread_est`, which is
    conservative (about 10x).
  - **Strict rule** (`pit_panel.lacking_securities`): a security that is ever a member is refused only if it has no
    volume at all, or if it has no quotes and is not on the `venue_scaled` fallback.
  - The 2011-2024 universe now loads under strict mode with no securities refused. Member-sessions by volume source:
    1,753,390 consolidated, 18,386 venue_scaled, 218 none. By spread source: 1,748,925 quoted, 18,380 estimator,
    4,689 missing (engine 0.2% fallback).
- **2026-11-20, amendment 5: implementation details fixed before fold 1 (no trial added).** Code:
  `pit_walk_forward.py`, `pit_evaluate.py`, tests in `tests/test_pit_walk_forward.py`. The features were frozen at
  22:59 UTC: `FEATURES` sha256 `f67687edae68f01af7cc5f639ac1f9ef153677773409ebd06567a68dc60dfc20`, features file sha256
  `5a82928639e454c968ef5901002939cdd63e03a7c10163ee201a59cffde75346`. That covers 832 securities and 2,250,049 rows, of
  which 1,664,254 are member rows.
  - **Features** (34): the `processor.py` OHLCV formulas computed on split-adjusted bars, using each security's valid
    bars only, plus SPY 1/5/20-session log returns and 20-session volatility.
    - Price levels (YesterdayClose, the MAs, the EMAs, the Bollinger bands) are expressed relative to the close, as in
      `walk_forward.py`. MACD and MACD_Signal are also divided by the close, because adjusted levels embed later splits.
      A test checks scale invariance.
    - Excluded: OBV, abnormal_volume_z (a duplicate of abnormal_vol) and the calendar fields (not OHLCV).
    - The 200-session MA warm-up means the first usable rows fall in late 2011. 107,551 member rows were dropped for
      warm-up or missing inputs.
  - **Labels:** forward log returns of the total-return-adjusted close (`TrClose`), counted in valid sessions.
  - **Forecasts:** produced for member rows only, since only member rows can be entered. The shuffle control therefore
    permutes signals across that day's members, as preregistered.
  - **Comparators:** scores are computed on `TrClose`. Each score is ranked among that day's members.
  - **Benchmarks:** the SPY benchmark is `spy_pit.csv` `tr_index`. The equal-weight universe holds the members as of
    t−1 and earns `TrClose` returns.
  - **Trial pool for the deflated Sharpe:** 39 Sharpes.
    - 28 earlier trials;
    - 2 from the old walk-forward;
    - 1 from the latency study (B);
    - 4 from the pre-close study (A–D, the annualized Sharpe of daily net excess);
    - 4 from this study (the LSTM, MOM12-1, MOM6-1 and REV1M).
  - **Test 5:** paired 20-session block bootstrap with the same resampled blocks for both return series.
  - **Not available:** sector exposure (the PIT layer has no PIT sector data). Market beta is reported.
- **2026-11-20, amendment 6: fixed vs validation-selected cutoff (user request, logged before any fold result was
  seen; evaluation only, no retraining).** Only the cutoff changes.
  - **Arm F (fixed):** the primary above, unchanged (`min_accepted` 0.25).
  - **Arm A (adaptive):** chooses the cutoff separately for each fold Y.
    - Run the identical PIT engine on that fold's seed-ensemble validation forecasts. That means next-open fills,
      member mask, spread, impact and fees, the ADV cap, $1M and 5 slots.
    - The panel ends the session before Y's first session, so no test-year price is read.
    - Choose `min_accepted` ∈ {0.20, 0.25, 0.30, 0.35} with the highest after-cost daily-return Sharpe. Ties, or a
      non-finite Sharpe at every cutoff, go to 0.25.
    - Freeze that choice for test year Y. The per-fold choices and validation Sharpes are reported.
    - Implementation: Arm A runs the same engine with the year-Y probabilities shifted by (0.25 − c_Y). For the long-only
      entry rule this is exactly equivalent to adj > c_Y, so one continuous 2016-2024 backtest serves each arm.
  - **Known limitation:** validation also drove early stopping, so validation Sharpes are optimistic. The bias is the
    same for every cutoff.
  - **Trials:** Arm A is one more trial, so **N = 40**, and the deflated Sharpe uses N = 40 for both arms. This replaces
    N = 39 above.
  - **Each arm** gets its own tests 1–5 and verdict.
  - **Comparison, reported for both arms:**
    - the paired 20-session block bootstrap (5,000 resamples) 95% CI of the Sharpe difference A − F;
    - the CAGR difference, max drawdown, turnover and cost breakdown;
    - the 2× spread with impact_k = 2 stress;
    - the year-by-year paired difference.
  - **Recipe for the single 2025 confirmation, fixed now:**
    - Arm A is the recipe only if all three hold:
      - (a) Arm A's verdict is "Edge supported";
      - (b) the paired Sharpe-difference CI excludes 0 in A's favour;
      - (c) A ≥ F in Sharpe under the 2× cost stress.
    - Otherwise the recipe is Arm F, if F is "Edge supported".
    - If neither arm is supported, there is no confirmation run and 2025 stays sealed.
    - The confirmation runs one arm only, once.
    - If the comparison is close or uncertain, the fixed 0.25 stays the research baseline.
- **2026-11-21, amendment 7: forecast batching and restart (implementation only; no trial added; no strategy
  result seen).**
  - **What happened:** the first launch was killed at about 01:19 when its parent app session ended. Only fold 2016
    finished. Its 3 jobs took about 90 minutes each, 98% of it in per-security eager MC-dropout calls.
  - **The change:** forecasting now batches rows across securities through one compiled call. It is the same
    estimator: 25 dropout-active passes, with mean and std per horizon. The jobs became about 12x faster (7.3 minutes
    for a 2016 job).
  - **Consistency:** so that every fold uses one code path, the 2016 outputs were archived unused in
    `wf_pit/archive_eager_forecast/` and all 27 jobs were rerun. Training is unchanged and deterministic. Every meta
    file records `code_sha256`.
  - **Threads:** 2016 seed 0 was rerun standalone with 15 threads. Every other job used the runner's 5 threads, which
    can change floating-point reduction order only.
  - **Detached runner:** the runner now runs as a detached process, so a session ending cannot stop it, and it resumes
    if restarted.
  - **Disclosure:** the job's console summary includes per-horizon test AUC. Those AUCs are model diagnostics, not
    strategy results, and nothing is selected on them.
- **Adapter status:** `pit_panel.py` with 18 passing tests in `tests/test_pit_panel.py`, covering:
  - AAPL's 4-for-1 split and $0.47 dividend;
  - the MRO 2011 and COP 2012 spin-offs;
  - the Motorola Mobility $40 cash merger;
  - the Concho to 1.46 ConocoPhillips stock merger;
  - the Nabors index deletion;
  - combined-event arithmetic and the settlement fallbacks.

  The full 2011-2024 panel builds with 186 split sessions, 131 distribution sessions, 27,857 cash dividends and
  137 settlements (75 with stock legs, 11 converted to cash because the successor is outside the panel). Six
  unverified demergers are excluded and counted.

## Known limitations
- **Impact coefficient:** k = 1.0 is an uncalibrated placeholder. The 2× stress reports the sensitivity.
- **Execution quotes:** spreads are estimated from daily bars; opening-auction spreads can be wider than estimated.
- **Membership history:** the S&P 500 membership history is reconstructed (acceptance tests M1-M5). Residual errors bias
  results only through the entry mask.
- **Settlements:** some settlement rows still carry "pending" or "parsed" statuses that the data layer accepted under S1
  and S2. Their values come from the documented fallback in `settlement_pit.csv`.
