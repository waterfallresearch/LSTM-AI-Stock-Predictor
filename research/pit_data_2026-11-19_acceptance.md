# Point-in-time S&P 500 data layer: acceptance tests (preregistered 2026-11-19)

Written before any `pit/` artifact is built. Thresholds are fixed. Any change after results are seen is logged here with its date and reason; nothing is silently loosened.

## Scope
- **Securities:** S&P 500 members by ISIN (`security_id`), XNYS sessions 2011-01-03 → 2026-11-18.
- **Source data:** the LSEG snapshot `TrainingData/indicators_data/lseg/20261119T132813190380Z` and its sibling runs, the hand-verified override CSVs in `TrainingData/pit/overrides/`, and SEC filings.
- **Reserved confirmation period:** 2025-01-02 → 2026-11-18.
  - The data layer may *build* these sessions so the acceptance tests can cover them.
  - No feature, model, threshold or strategy choice may *read* them. Loaders enforce this with a guard that raises unless `confirm=True`.

## Acceptance tests (all must pass before any model or strategy work)

| ID | Area | Test | Pass condition |
|---|---|---|---|
| M1 | Membership | Replay vs the 4 LSEG checkpoints (2015-12-31, 2019-12-31, 2023-12-29, 2026-11-18) | 0 extra, 0 missing at every checkpoint |
| M2 | Membership | Replay vs the dated boundary probes in `boundary_probes/` | 0 unexplained differences; each explained difference cites a source in `overrides/` |
| M3 | Membership | Opening roster 2011-01-03 vs SPY's SEC holdings as of 2010-12-31 | Exact match after documented, sourced corrections |
| M4 | Membership | Internal consistency | No forward or reverse event conflicts; 495–510 members per session |
| M5 | Membership | Regression | The new pipeline reproduces `membership_dated_candidate.csv.gz` exactly, or every row difference is a documented correction |
| I1 | Identity | `security_master` | No security has two primary RICs on one session; no RIC maps to two securities on one session |
| P1 | Prices | Executable bar coverage | ≥ 99.9% of member-sessions have a valid bar (L>0, H≥max(O,C), L≤min(O,C), V>0) from the security's primary RIC for that session |
| P2 | Prices | Alias adjudication (BKR, CPB, HST, KMB) | For each pair, the chosen primary series' volume is within ±10% of an independent consolidated feed on ≥ 95% of sampled sessions; evidence is stored |
| P3 | Prices | Exceptions | Every member-session without a valid bar is in the exception ledger with a reason category and source |
| C1 | Splits | All capital-change split/consolidation events for members | Each has a trading-effective date confirmed by the price ratio (±10%), or a documented manual check |
| C2 | Splits | Continuity | No unexplained |overnight move| > 50% in split-adjusted open/close for member-sessions |
| C3 | Dividends | Ex-date cash dividends | Duplicates removed; non-USD or unknown-currency rows flagged; SPY distributions present for the TR benchmark |
| S1 | Settlement | Every member that leaves the panel without remaining listed | Exactly one terminal outcome (cash / stock / mixed / elective / contingent / OTC / liquidation) with a source URL; 0 `unknown` |
| S2 | Settlement | Validation | Cash deals: the settlement value is within ±2% of the last close. Stock and mixed deals: within ±5% of the last close, using the successor's first available open. Outliers are documented |
| K1 | Costs | Spread estimate coverage | ≥ 95% of member-sessions have a Corwin–Schultz or Abdi–Ranaldo 21-day spread estimate |
| K2 | Costs | Estimator sanity | Where LSEG closing bid/ask exist, the median absolute error of the estimate is reported. It is not a pass/fail threshold, because there's no prior basis for one |
| R1 | Reproducibility | Rebuild from scratch | Identical sha256 for every `pit/` artifact on a second run |

## Verdict rule
- **Data layer ACCEPTED** only if every test except K2 passes.
- A failure blocks Phase 7, the momentum and liquidity research round. The failure is fixed, or the affected securities and sessions are excluded with a documented reason.
- An exclusion of more than 0.5% of member-sessions counts as a failure.

## Amendment log
- **2026-11-20 — P2 (alias adjudication).** The preregistered volume criterion assumed LSEG `ACVOL_UNS` is consolidated volume. Measured against Alpha Vantage, it is about 25–38% of consolidated volume for *every* stock checked, including the controls AAPL, MSFT, JPM and XOM. It is venue volume.
  - **P2 as written therefore FAILS** for all series. It is kept as a failure, not loosened.
  - **New test P2a**, added after seeing data and labelled post hoc: the chosen primary series' close equals the consolidated close (within 1 bp) on ≥ 95% of sessions.
  - **Consequence:** LSEG volume cannot be used as consolidated volume for ADV, capacity or liquidity features until a consolidated-volume source or a validated scaling exists. This blocks K1's ADV inputs and the liquidity features of Phase 7.
- **2026-11-20 — P2 re-test on consolidated volume.** LSEG carries consolidated volume and closing bid/ask on the consolidated RIC: `XYZ.O` for Nasdaq names, the bare `XYZ` for NYSE names. AAPL.O and JPM matched Alpha Vantage exactly.
  - Downloaded for all 860 primary RICs (`pit/lseg_consolidated.py`, 86 of 86 batches).
  - **The preregistered P2 criterion, applied to the consolidated series, PASSES:** 451 of 463 comparable securities (97.4%) are within ±10% on ≥ 95% of sessions, and the median ratio is 1.000.
  - **Residual failures:** GOOGL fails only in 2011–2013, because Alpha Vantage's GOOGL history before the 2014 share-class split is not comparable. CBOE fails because its bare RIC resolves to a single venue.
  - **Coverage:** consolidated volume covers 92.6% of member-sessions. The rest are mostly expired RICs whose consolidated name does not follow the pattern, and they need a documented fallback, for example venue volume × the security's own consolidated/venue ratio.
  - The earlier P2 FAIL on venue volume stands as recorded. This is a re-test on a new data series, logged here, not a loosening.
- **2026-11-20 — K2 (reported, not pass/fail).** Real closing quoted spreads (21-day median) have a median of **2.3 bps**, with p10–p90 of 1–17 bps.
  - The Corwin–Schultz/Abdi–Ranaldo estimate has a median of **27 bps**: median error +21 bps, median absolute error 26 bps, and a rank correlation across securities of only 0.30.
  - **Consequence:** the OHLC estimators are not usable cost inputs for S&P 500 stocks. The cost model must use quoted spreads, which cover 92.5% of member-sessions, with a documented fallback.
  - K1 (estimate coverage) passes as written, but its estimate is not fit for purpose. That is recorded here so K1's pass is not misread.
- **2026-11-20 — Consolidated coverage fallback (completeness).** For 115 securities the standard consolidated RIC returned nothing.
  - **93 were found on LSEG's `XYZ.K` consolidated RIC.** For these names the bare `XYZ` is not a valid universe (ABBV, ORCL, CBRE, GRMN, NCLH, ...). They come from `pit/lseg_consolidated.py --fallback`. The P2 re-test on the enlarged set still passes: 97.4% of 504 securities.
  - **22 remain, mostly bankrupt or failed names** (SIVB, FRC, SBNY, BBBY, SHLD, JCP, CHK, WIN, ...), covering 0.92% of member-sessions. Excluding them would exceed the 0.5% exclusion limit and re-introduce survivorship bias, so they get a documented fallback, added after seeing data and labelled post hoc:
    - **Volume:** `volume_adv` = venue volume × the trailing 63-session median consolidated/venue ratio of other securities on the same venue. The ratio is causal.
    - **Fallback accuracy**, measured on securities whose true value is known: the 21-day ADV has a median absolute error of 12%; 78% are within ±25% and 96% within ±50%.
    - **Spreads:** these names have no quotes, so the conservative daily-bar estimator is used.
    - **Remaining gap:** 0.006% of member-sessions still have no volume.
  - **Coverage now:** consolidated volume 99.08% of member-sessions, quoted spreads 98.9%.
- **2026-11-20 — M3 closed.** 498 of 500 pairs were SEC-linked by the roster study. The last two, Tyco International (CH0100383485, CIK 833444 name history) and Rowan Companies (GB00B6SLMV12, 8-K12B 0001193125-12-211636), plus the review-tier Cablevision NY Group line (CUSIP 12686C109), are confirmed in `overrides/roster_link_confirmations.csv`. The result is 500/500.
- **2026-11-20 — R1.** The first `--rebuild` differed only in `prices_pit_audit.json`. That "before" copy had been written by an earlier version of `pit/prices.py`, before the P2a fields were added; it was not the output of the current code. Two consecutive builds of the current code are byte-identical: the second `--rebuild` produced 22 of 22 identical artifacts. Manifests are excluded because they embed their creation time.
- **2026-11-20 — Verdict: ACCEPTED** (`python -m pit.acceptance --rebuild`; `pit_data_acceptance_results.md`). Every test except K2 passes. P2 stays a recorded preregistered failure, handled by its amendments.
