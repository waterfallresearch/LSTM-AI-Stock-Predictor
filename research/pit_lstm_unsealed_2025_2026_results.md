# Old LSTM rule on 2025-01-02 → 2026-11-18: results

**Reading (fixed in advance): not consistent with the development result.** The frozen p − σ > 0.25 rule lost 27.1% while SPY total return gained 27.3%. The run was owner-unsealed and is descriptive only; it is trial 57. The reserved 2025 confirmation window is now spent.

| 2025-01-02 → 2026-11-18, net of costs | Old rule | SPY total return | Raw top-decile (context) |
|---|---:|---:|---:|
| Total return | −27.1% | +27.3% | +48.1% |
| CAGR | −15.6% | +13.8% | +23.4% |
| Annualized Sharpe | −0.70 | 0.84 | 0.81 |
| Max drawdown | −30.9% | −18.8% | −29.7% |
| Trades | 35 | | 64 |

| Window | Old rule | SPY TR | Raw top-decile |
|---|---:|---:|---:|
| 2025 calendar year | −14.1% | +18.0% | +20.3% |
| 2026 to 2026-11-18 | −15.2% | +7.9% | +23.1% |
| Original sealed window 2025-01-02 → 2025-11-18 | −17.6% | +13.9% | +12.9% |

- Paired Sharpe difference vs SPY −1.54 (one-sided 95% lower bound −2.85); vs the raw top-decile −1.51 (lower bound −2.47). Moving-block bootstrap, 5,000 draws of 20 sessions, seed 20261123.
- Cost stress (2× spread, 2× impact) Sharpe −0.73; without the three largest winners −0.92. Deflated Sharpe 0.012 at 57 trials.
- 35 trades, win rate 37.1%, 90.3% of days invested, $7,953 total costs. Horizons: 13 one-week, 12 six-month, 6 one-day, 4 one-month. The five largest losses were six-month holds (−37%, −22%, −21%, −16%, −18%).
- Forecast skill did not vanish. Test AUC on realized labels was 0.53–0.62 at the 1-day, 1-week and 1-month horizons and about 0.50 at 6 months. The same forecasts ranked by raw probability (top decile, σ ignored) returned +48.1%. The loss comes from what the p − σ > 0.25 filter selected, consistent with the earlier findings that σ does not flag worse forecasts and that the rule's development gains rested on a few trades.
- Inputs: the extended feature file reproduced all 2,250,049 frozen 2011–2024 rows exactly. Training samples 65,323 (2025 fold) and 71,314 (2026 fold); validation AUC 0.577–0.600 and 0.557–0.569. Eligible security-days 236,467 of 236,535.

The raw top-decile figure is context only. It was not the registered arm, and promoting it after seeing this window would be selection on the outcome. It failed its own 2016–2024 gate (Sharpe 0.30, max drawdown −71.7%).

**Conclusion.** The old LSTM rule is not supported on development data and lost money out of sample. It should not be paper-traded as a candidate without a new hypothesis tested on unseen data. No untouched pre-2026-11-19 data remains, so any future confirmation must use fresh data (forward paper trading) or new history (for example CRSP 2000–2015 as new walk-forward test years).

- Results SHA-256 `8685ee52aec4cb7dc5c1c059adb603425cc947b346c0df01f8f5ab144467ff52` (`wf_pit_unsealed_2025_2026/results.json`).
- Runner SHA-256 `9ac4d0c70e426ecfe3ef9a0ef3e4989173e4c1bccc0bc5ef196f97479e2e6e82` (`pit_unsealed_2025_2026.py`).
- Preregistration SHA-256 `e1ac9976fd564539e2f910b159db77aceb95364817b1e8a0467c3920a282e57d`.
- Deviation: a one-line bug fix in the feature `prepare` step (`df.isin` → `df["isin"]`) after the parity check passed and before any model was trained. No forecast, trade or return existed at that point.
