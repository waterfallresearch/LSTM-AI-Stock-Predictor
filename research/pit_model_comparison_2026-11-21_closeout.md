# Point-in-time model comparison closeout

The 2016–2024 development comparison completed 45 fits on shared boundary-checked samples. Its trial ledger contains 45 portfolio configurations across the current and prior research. Those are two distinct counts. The final pre-score manifest records the fitted forecasts and input hashes. All four strategies shared daily next-open execution, the five-slot cap, costs and common trade eligibility. The LSTM probability-only arm used the maximum horizon probability and a common top-decile selection rule.

| Strategy | Net CAGR | Net Sharpe | Max drawdown | Trades | Stress Sharpe | Sharpe excluding three best trades |
|---|---:|---:|---:|---:|---:|---:|
| LSTM | 4.59% | 0.303 | -71.70% | 319 | 0.268 | 0.245 |
| L2 logistic regression | 2.40% | 0.245 | -69.98% | 308 | 0.196 | 0.272 |
| LightGBM | 8.98% | 0.447 | -37.28% | 184 | 0.414 | 0.269 |
| Six-month momentum | 8.11% | 0.408 | -47.56% | 517 | 0.348 | 0.311 |
| SPY total return | 14.61% | 0.854 | -33.70% | | | |

The LSTM failed all four advancement checks. Its Deflated Sharpe was 0.030 against a 0.95 threshold. The paired Sharpe-difference intervals against logistic regression, LightGBM and momentum all included zero. No recipe advanced and the reserved 2025 period stayed sealed.

| Fitted model | Equal-horizon daily rank IC | Brier score |
|---|---:|---:|
| LSTM | 0.0520 | 0.13274 |
| LightGBM | 0.0481 | 0.13325 |
| L2 logistic regression | 0.0222 | 0.16178 |

The descriptive LSTM-minus-LightGBM forecast IC difference was +0.0039, with a paired interval from -0.0022 to +0.0101. The old uncertainty-adjusted 19.65% LSTM CAGR used a different entry rule, sample construction and trade eligibility. The difference between that result and this study cannot be attributed to portfolio concentration alone. This study compared model families under a five-position cap, so whether broader portfolios improve their results remains an open hypothesis.

Independent checks reproduced each strategy's Sharpe and drawdown from saved equity paths and verified that signal dates precede fills. Claude reviewed the results and agreed that the LSTM fails the advancement gate. The preregistration and the local evaluation directory contain the detailed protocol, JSON results, pre-score manifest, daily forecast metrics, equity paths and trade ledgers.

## Next research decision

The next portfolio experiment should isolate breadth. Use the frozen single-horizon six-month momentum ranking, same historical eligibility, and one common rebalance, cost and sizing convention for a five-name control versus a prespecified equal-weight broad long-only basket. Match gross exposure and use next-open execution, realistic spreads, impact, fees, participation caps, and corporate-action handling. Set the breadth, rebalance calendar, paired after-cost effect size, block bootstrap and sensitivity gates in a distinct preregistration before running. Keep the 2016–2024 evaluation in development and carry forward the prior trial count of 45. A long-short arm needs its own coverage and borrow-cost validation before treating returns as executable.

Continue validating fundamentals in parallel. The dual-feed pilot provides SEC-checked quarterly revenue, with dated WRDS snapshots and a separately labeled LSEG reconstruction when exact filing evidence supports it. The pilot covers three quarters and does not yet validate the full historical identity crosswalk or metric coverage. Keep this work independent of the portfolio breadth change. A subsequent feature comparison can hold the selected basket rules and model fixed while adding a small validated fundamentals block.

## Local artifact fingerprints

- `forecast_daily.csv.gz` SHA-256 `c2dcb3035f05acad006480695cdedafbfcaaa4b3fb5b6e80414b228c8e44eb97`
- `lightgbm_equity.csv` SHA-256 `730cbb8130c79ad44f0e69f9d7216118c06395555515d856fdad78935693b56e`
- `lightgbm_trades.csv` SHA-256 `d470f84af68e217f56e3a3e4b73082cb81ea6a506c460f13816add118f07864c`
- `logistic_equity.csv` SHA-256 `3073c98ad8bfd961880a1514e347728b0af96c883e88093710bce679c3796900`
- `logistic_trades.csv` SHA-256 `03a7647bf4ec8af9ce0775970da925d7b1fcdef366b140c0dd45171a658dbc61`
- `lstm_equity.csv` SHA-256 `2677c7f804383df4ddac15746d0c0966e1f55fbf9162625d54b7eed33d2c1de2`
- `lstm_trades.csv` SHA-256 `5154f25f28a9b52d4dd08acb3dd45a429be154f30356b97c21e54d9b5c8f07e7`
- `momentum_equity.csv` SHA-256 `5a63111606e479ece82b2671ac3d512f2600f438d9ba73c8aa31e06c269ee2b1`
- `momentum_trades.csv` SHA-256 `d782f302be83dd6c466d5df260aa842f035c5d745b0a09da9caf29eb81e1df42`
- `prescore_manifest.json` SHA-256 `0b7b8537e6e424620e552dd27b110fd9554fe785423439c57a2fef113230adbb`
- `results.json` SHA-256 `201195d0be93fed586bd7e2afbcca3184d11a7cfa9fd1deff2ac6efe7102d7f7`
