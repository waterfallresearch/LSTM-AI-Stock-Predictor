# PIT S&P 500 next-open study: results (2026-11-21)

Preregistration: `pit_nextopen_2026-11-20_preregistration.md`, including amendments 1-7. Raw output:
`pit_nextopen_2026-11-20_results.json`, trades `pit_nextopen_2026-11-20_trades_{F,A}.csv`.

## How it was run
- Evaluated **once** with `pit_evaluate.py --shuffles 500 --boot 5000`.
- 27 jobs: 9 folds × 3 seeds, all on one code hash and one feature hash. Feature list sha256 `f67687ed…`, features file
  sha256 `5a829286…`.
- Window 2016-01-04 → 2024-12-31 on a survivorship-free S&P 500 universe of 849 securities in the panel.
- Fills at the next open; $1M start; 5 slots.
- Costs: spread, square-root impact (k = 1), SEC and FINRA fees, and a 5% ADV cap.
- **Trial count N = 40.**

## Verdict: **Edge not supported** for both arms. No confirmation run; 2025-01-02 → 2025-11-18 stays sealed.

| Test (pass rule) | Arm F, fixed 0.25 (primary) | Arm A, cutoff chosen on validation |
|---|---|---|
| 1. CAGR > SPY TR (+14.6%) | **+19.7%** pass | +2.4% fail |
| 2. Shuffle control (500), p ≤ 0.05 | p = **0.024** pass | p = 0.99 fail |
| 3. Block-bootstrap Sharpe 95% CI excludes 0 | 0.90, CI [0.36, 1.65] pass | 0.22, CI [−0.42, 1.05] fail |
| 4. Deflated Sharpe ≥ 0.95 (N = 40) | **0.44** fail (SR₀ = 0.95 annualized) | 0.02 fail |
| 5. Beats best simple ranking (MOM6-1, 0.41), paired CI excludes 0 | diff CI [−0.17, 1.29] fail | diff CI [−0.93, 0.67] fail |

**Confirmation recipe (amendment 6 rule):** none.
- Arm A is not supported. Its Sharpe difference from F is −0.68, CI [−1.26, −0.18], which is significantly worse.
- Arm F fails tests 4 and 5. "Edge not supported" applies because test 4 is among the required tests 1-4.

## Benchmarks and comparators (same engine and costs, 2016-2024)

| | CAGR | Sharpe | Max DD |
|---|---|---|---|
| SPY total return | +14.6% | 0.85 | −33.7% |
| Equal-weight members (no costs) | +12.4% | 0.71 | −40.0% |
| **LSTM, arm F** | **+19.7%** | **0.90** | −31.7% |
| LSTM, arm A | +2.4% | 0.22 | −52.3% |
| MOM12-1 | +4.5% | 0.30 | |
| MOM6-1 | +8.1% | 0.41 | |
| REV1M | +3.0% | 0.27 | |

## Why arm F's headline is not evidence of an edge
1. **Multiple testing.** After 40 trials, the expected best Sharpe under no skill (SR₀) is 0.95, and F's 0.90 is below
   it. Against zero alone F looks real (PSR 0.997), but not against the search that produced it.
2. **The return comes from few trades.**
   - The top 3 trades made $1.54M of the $4.01M gain. Without them CAGR is **+14.8%, equal to SPY**.
   - 2023 alone returned +75.9%.
   - F beat SPY in only 4 of 9 years: 2020, 2022, 2023 and 2024.
3. **It is fragile to arbitrary choices.**
   - **Seeds:** the three seeds' Sharpes are 0.67, 0.13 and 0.74.
   - **Cutoff:** moving the cutoff by ±0.05 per year (arm A) collapses the CAGR from +19.7% to +2.4%, at the same
     turnover (13 times a year). A real ranking edge should not depend on the exact cutoff.
   - **Validation:** validation Sharpes did not predict test performance. The validation-best cutoff was worse than
     the fixed one in 6 of 9 years.
4. **It behaves like the market.**
   - Beta to SPY TR is 0.76 and time in market is 85%.
   - Sharpe 0.90 is about SPY's 0.85.
   - Much of the return is equity exposure plus a few large winners.

## What does hold up (informational)
- **Not a timing artifact.** The same signals filled at next close give +20.2% CAGR and Sharpe 0.92. The old
  same-close inflation does not apply here.
- **Costs are realistic and not decisive.** Total costs were $217k: impact $184k, spread $31k, fees $2k. Turnover was
  13.3 times a year. Under the 2× spread with impact k = 2 stress, CAGR is +18.3% and Sharpe 0.85. No entries were
  blocked or shrunk by the ADV cap, and no spread fallback was used.
- **Model diagnostics.** Test AUCs (seed 0) were mostly 0.53-0.65 at 1w/1m horizons and about 0.50-0.58 at 1d. That is
  some ranking information, which is consistent with passing the shuffle test. It is not strong enough to survive the
  deflation and the comparison with simple factors.

## Adaptive-cutoff arm (amendment 6)
- **Cutoffs chosen per fold:**

  | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 |
  |---|---|---|---|---|---|---|---|---|
  | 0.30 | 0.35 | 0.25 | 0.20 | 0.20 | 0.25 | 0.30 | 0.20 | 0.30 |

- Validation baskets were small, 10-65 trades per cutoff per year, so the choices were noisy.
- **Comparison A − F:**
  - Sharpe −0.68, CI [−1.26, −0.18];
  - CAGR −17.2 points;
  - max drawdown −52.3% vs −31.7%;
  - turnover 12.9 vs 13.3 a year;
  - stressed Sharpe 0.18 vs 0.85.
- **Year by year (A − F, total-return points):**

  | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 |
  |---|---|---|---|---|---|---|---|---|
  | +1.4 | −10.1 | +2.6 | −11.9 | −27.1 | +0.4 | −26.8 | −87.0 | −8.3 |
- **Conclusion:** keep fixed 0.25 as the research baseline, as the amendment specified. Selecting a cutoff on
  validation adds a trial and loses.

## Data and process notes
- **Universe:** 99.08% of member-sessions have consolidated volume. 22 failed or bankrupt names use the scaled-venue
  volume fallback (amendment 4).
- **Training rows dropped:** about 100 per fold had a label window past the security's last bar.
- **Amendment 7:** the first launch was killed when the app session ended. Forecasting was then batched, which is the
  same estimator, and all 27 jobs were rerun in about 2h20m. The 2016 outputs from the earlier code were archived
  unused.
- **Not available:** sector exposure, because there is no point-in-time sector data.

## Trial accounting
N = 40 for this study. The next-close timing diagnostic counts as one more, so **N = 41 for any later study**.

## Bottom line
On survivorship-free data with realistic execution, the LSTM ranking shows some information: it passes the shuffle
test and its Sharpe CI excludes 0. But the evidence does not support a tradable edge:
- it fails the deflated Sharpe at N = 40;
- it does not beat 6-month momentum with confidence;
- its outperformance over SPY rests on three trades and one year;
- small changes in cutoff or seed erase it.

This agrees with the earlier audit verdict. The 2025 confirmation period stays sealed. It should be spent only on a
recipe that first passes tests 1-4 on 2016-2024.
