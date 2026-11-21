# Price-rank composite preregistration

Registered after the completed breadth study and before scoring this new recipe. The chosen portfolio for this experiment is the five-name control, since breadth did not advance. This is a signal test in observed development history (2016–2024). 2025 stays sealed.

Economic hypothesis: combine persistence, short-run reversal, lower risk and easier execution to improve net ranking performance over six-month momentum. The null is no positive paired net Sharpe improvement. On the same 107 month-end signal dates, use the same eligible universe as the breadth test, additionally requiring finite values for the control and all four component ranks. Apply the same common eligible mask to both arms. The control is TR[t-21]/TR[t-126]-1. The composite takes the mean of cross-sectional average-tie percentile ranks of these four inputs:

- TR[t-21]/TR[t-252]-1 (12-1 total-return momentum).
- -(TR[t-1]/TR[t-21]-1) (one-month reversal).
- Negative standard deviation of the 63 daily total returns ending at t-1 (no forward-filling).
- Mean daily raw close times consolidated-or-documented-fallback volume over the 20 sessions ending at t-1 (all 20 valid).

Rank higher scores first, breaking final ties by ascending dated ISIN. Buy up to five names with a 20% target per name and the same next-open, rebalance, settlement, cash, costs (including assumed 1 bp commission), ADV, stress and top-three diagnostics defined in the breadth preregistration. Final positions are marked at the last 2024 close. No new signal, parameter, or alternative rank weighting is tried.

The narrower common eligibility makes the control a new scored arm. Carry forward all 47 earlier Sharpes, add two arms for N=49, and verify prior fingerprints and count before running. Advance only if composite minus control net annualized Sharpe is at least 0.20, exceeds zero on the one-sided 95% paired 20-session moving-block lower bound (5,000 draws, seed 20261121), composite DSR is at least 0.95, and paired Sharpe remains positive under cost stress and winner removal. Report two-sided interval, CAGR, drawdown, turnover, exposure, trade and cost data, and descriptive monthly rank IC against next-open-to-following-rebalance-open total returns on executable matched names. SPY total return is contextual. Failure ends this recipe. Earnings, fundamentals and models beyond the fixed rank composite are separate gated stages, with no confirmation access.

The predecessor breadth results file is pinned to SHA-256 b53b3b90ee05be4ec14374e1f6996dd3a7647d5fdba064fd7904cb496d8562fd. Recheck every trial input hash from its pre-score manifest before loading the trial pool.
