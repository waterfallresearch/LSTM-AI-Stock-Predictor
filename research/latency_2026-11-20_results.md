# Execution-latency attribution: results (run 2026-11-20)

- **Preregistration:** `latency_2026-11-20_preregistration.md` (written before the run; no changes after).
- **Code:** `latency_attribution.py` (9 tests in `tests/test_latency_attribution.py`), engine `backtest_core.py`.
- **Raw output:** `latency_2026-11-20_results.json`. Trades, A-trade decompositions and event tables are in
  `latency_2026-11-20_*.csv.gz`.
- **Trial count:** N = 31 (B = `next_open` is the only new configuration).

## Reproduction checks: PASS
- Legacy A = +37.0% / 30 trades, C = +13.8% / 25 trades.
- Walk-forward C = 142 trades, CAGR +13.1% (matches `walkforward_2026-11-19_results.json`).

## Headline
- **The 23-point legacy gap is a selection effect, not an execution-price effect.** Only 15 of A's 30 trades also
  occur in C. Replaying A's own 30 trades with the next-close entry would have earned *more* than A did (sum of gross
  log returns 1.34 vs 1.24). The gap comes from A and C ending up holding different trades, which is luck in a
  25-30 trade sample. H1 is rejected on the legacy set.
- **Over 2016-2023 (walk-forward, 142-169 trades) the timing effect is small at the portfolio level:**
  - same close: CAGR 14.0%
  - next open: CAGR 15.0%
  - next close: CAGR 13.1%
  The next-open fill, which is implementable with daily data, is the best of the three.
- **At the signal level there is a real entry-timing effect, mostly in the next session:**
  - Entering at close t instead of close t+1 is worth +27.6 bp per signal (Newey-West t = 4.3, positive in all 8 years).
  - About 70% of that (+19.3 bp, t = 2.8) is earned between the next open and the next close, which a next-open entry
    already captures.
  - The overnight part, the only piece that needs a same-day close entry, is +8.4 bp (t = 1.8, not significant).
- **Signals fire after the stock lags on day t.** The day-t open-to-close excess is -49 bp (t = -4.9). The next-session
  gain is concentrated after down days (+23.0 bp, t = 3.1) versus after up days (+8.5 bp, t = 0.9). This pattern is
  consistent with short-term reversal.

## Part 1a: portfolio runs (frozen rules; only `fill` changes)

| Set | Run | Total return | CAGR | Sharpe (95% CI) | Max DD | Trades | Costs $ |
|---|---|---|---|---|---|---|---|
| Legacy 2021-06-11..2023-06-30 | A same close | +37.0% | +16.6% | 0.77 [-0.59, 2.10] | -23.7% | 30 | 149 |
| | B next open | +15.2% | +7.2% | 0.39 [-0.96, 1.71] | -27.7% | 27 | 129 |
| | C next close | +13.8% | +6.5% | 0.38 [-1.01, 1.67] | -25.9% | 25 | 117 |
| Walk-forward 2016-2023 | A same close | +181.7% | +14.0% | 0.75 [0.08, 1.41] | -28.2% | 169 | 1,608 |
| | B next open | +200.5% | +15.0% | 0.80 [0.14, 1.50] | -26.1% | 142 | 1,359 |
| | C next close | +164.5% | +13.1% | 0.72 [0.05, 1.44] | -28.9% | 142 | 1,250 |

The bootstrap CIs of all three runs overlap almost entirely on both sets.

## Part 1b: decomposition of A's trades (gross log returns, summed over trades)

| Set | Trades | Total | Overnight (close t -> open t+1) | Next session (open -> close t+1) | Rest (close t+1 -> exit) |
|---|---|---|---|---|---|
| Legacy | 30 | 1.239 | -0.091* | 0.0003* | 1.339 |
| Walk-forward | 169 | 4.110 | 0.291 | 0.107 | 3.712 |

*Legacy overnight and next-session terms cover 28 of 30 trades. The other 2 are in tickers whose Opens were rejected
(see limitations). Their combined close t -> close t+1 gap, which needs no Opens, is -0.100 over all 30 trades. The
total and rest terms use closes only and are complete.

| Set | A's trades replayed with C entry | C portfolio | Selection effect (C) | Trades matched A vs C | Only A | Only C |
|---|---|---|---|---|---|---|
| Legacy | 1.339 | 0.331 | **-1.008** | 15 | 15 | 10 |
| Walk-forward | 3.712 | 3.930 | +0.218 | 118 | 51 | 24 |

How to read this:
- **Legacy:** on the same trades, the later entry was not worse (1.339 vs 1.239). The whole gap is that C held
  different, worse trades (selection -1.008).
- **Walk-forward:**
  - On A's own trades, the earlier entry is worth 0.398 log (about 24 bp per trade).
  - C's different trade selection recovers 0.218 of that.
  - So the net same-close advantage is 0.18 log over eight years.

## Part 1c: signal-level event study (primary: split-flagged events excluded; none were flagged)
Mean of the daily average excess return versus the equal-weight eligible universe, with Newey-West t (10 lags).

| Component | Legacy (2,291 events) | Walk-forward (5,740 events) |
|---|---|---|
| Day t open -> close (inside the signal) | -114.1 bp (t -5.62) | -49.2 bp (t -4.89) |
| **Gap: close t -> close t+1 (A over C)** | +15.2 bp (t 1.36) | **+27.6 bp (t 4.31)** |
| Overnight: close t -> open t+1 | +3.2 bp (t 0.52) | +8.4 bp (t 1.80) |
| Next session: open t+1 -> close t+1 | +9.8 bp (t 1.14) | +19.3 bp (t 2.80) |
| After entry: close t+1 -> close t+1+h | +657 bp (t 4.62) | +576 bp (t 5.26) |

### Walk-forward gap by year (bp)

| Year | Gap | Overnight part |
|---|---|---|
| 2016 | 19.0 | 4.8 |
| 2017 | 24.1 | 14.5 |
| 2018 | 17.0 | 6.9 |
| 2019 | 11.3 | 7.0 |
| 2020 | 34.0 | -12.8 |
| 2021 | 37.0 | -4.1 |
| 2022 | 59.7 | -0.8 |
| 2023 | 78.0 | 82.4 |

### Walk-forward split by the sign of day t's close-to-close return

| Day t | Gap | Overnight part | Next-session part | Events |
|---|---|---|---|---|
| Down | +30.6 bp (t 3.87) | +7.6 bp (t 1.39) | +23.0 bp (t 3.07) | 3,041 |
| Up | +15.7 bp (t 1.80) | +7.2 bp (t 1.76) | +8.5 bp (t 0.90) | 2,673 |

## Gate G1 (walk-forward, preregistered): PASS

| Check | Required | Observed | Result |
|---|---|---|---|
| Mean excess gap | >= 20 bp | 27.6 bp | pass |
| Newey-West t | >= 2.0 | 4.31 | pass |
| Positive years | >= 5 of 8 | 8 of 8 | pass |

By the preregistered rule this unlocks Stage 2 (the LSEG intraday probe).

**Weakness found in the gate after seeing results (recorded, not acted on):**
- G1 compares a same-close entry with a *next-close* entry. The implementable daily alternative turned out to be the
  *next-open* entry, which already captures the next-session part.
- The part only a pre-close order can add over next-open is the overnight component: +8.4 bp, t = 1.8, below the 20 bp
  floor, and negative in 2020-2022.
- A 3:40 PM model would also capture only part of that, because some of day t's information arrives after 3:40.
- So the measured upside of the intraday build over a next-open daily strategy is small and statistically weak.
- The gate is not changed here. The next preregistration (Stage 3, if it ever runs) must use next-open (B), not
  next-close (C), as the comparator.

## Stage 2: LSEG intraday probe and gate G2: FAIL
- **Probe:** `TrainingData/lseg_intraday_probe.py`, run 2026-11-20 with lseg-data 2.1.1 (desktop session, system
  Python 3.13, which has the package; the research venv does not). Manifest:
  `TrainingData/indicators_data/lseg/intraday_probe/20261120T143834552684Z/manifest.json` (gitignored).
- **Requests:** 10 RICs (AAPL.O, MSFT.O, JPM.N, XOM.N, A.N, AA.N, AAL.OQ, AAP.N, BSX.N, delisted AABA.OQ^J19) x
  5-minute and 1-minute bars x 7-day windows starting 2016-03-01, 2019-03-01, 2021-03-01, 2023-03-01 and 2024-12-02.
- **Result:** all 100 requests returned **zero bars**, with no error, including the December 2024 window.
- **The session itself worked:** daily history in the same session returned 15-17 fields per live RIC.
  - Fields returned: TRDPRC_1, OPEN_PRC, HIGH_1, LOW_1, ACVOL_UNS, BID, ASK, VWAP, TRNOVR_UNS, NUM_MOVES, ...
  - CLS_AUCVOL / OPN_AUCVOL (auction volumes) appear for the Nasdaq name only.
  - No separate closing-auction *price* field was returned.
  - The delisted RIC returned nothing.
- **Reading:** the entitlement's intraday history does not reach back to 2024 or earlier (consistent with a rolling
  retention window shorter than about two years). Recent windows were deliberately not requested, because they fall in
  the reserved confirmation period. So it is unverified that intraday requests work at all on this entitlement; the
  first forward-recording day would confirm it.
- **G2 decision:** FAIL. A pre-2025 backtest of a 3:40 PM model is not possible with this entitlement. Per the
  preregistration, the only route to evaluating it is forward recording.

### Follow-up probe of 2025-2026 coverage (user request, 2026-11-20)
- **Why:** the user asked to confirm that intraday requests work, using 2025 to now.
- **What was kept:** run with `--reserved-coverage`, which stores only coverage metadata (counts, timestamps, columns).
  No prices or returns from the reserved period were kept or looked at.
- **Manifest:** `TrainingData/indicators_data/lseg/intraday_probe/20261120T144651782138Z/manifest.json`.
- **Requests:** windows starting 2025-01-06, 2025-06-02, 2025-11-17, 2026-05-04 and 2026-11-09.

Results:
- **Intraday requests work.** All 9 live RICs return 1-minute and 5-minute bars from **2025-11-19** onward; the
  2025-01 and 2025-06 windows are empty. The entitlement keeps a rolling window of about one year. The delisted RIC
  returns nothing.
- **Timestamps** are naive UTC and include extended hours (bars from about 08:00 to 20:00 New York time), so the
  15:40 New York bar is present. The script's `has_1535_or_1540_bar` flag assumed tz-aware times and is not meaningful
  for this output.
- **Per-bar fields:** OPEN_PRC, HIGH_1, LOW_1, TRDPRC_1, ACVOL_UNS, VWAP, NUM_MOVES, plus quote fields (BID, ASK,
  OPEN_BID/ASK, BID/ASK_HIGH_1/LOW_1, BID/ASK_NUMMOV). A 15:40 snapshot would therefore include a real quoted spread.
- **G2 stays FAIL:** none of this history is before 2025-01-02.

Consequences:
- The only historical window for a 3:40 PM test is 2025-11-19 → 2026-11-18. That is about 250 sessions, current
  listings only (survivorship bias), and entirely inside the reserved confirmation period. Using it for research would
  use up that confirmation year.
- **The window rolls:** every day, the oldest day of intraday history is lost. If the pre-close idea is kept, the
  history has to be archived locally from now on (forward recording).

## Interpretation
1. **The +37% vs +13.8% legacy contrast should not be used as evidence for an intraday edge.** It is mostly a
   different set of 25-30 trades.
2. **Over eight years, filling at the next open is at least as good as the look-ahead same-close fill.** That is the
   configuration the PIT study already planned (`StrategyParams.pit()`).
3. **The signal behaves partly like short-term reversal.** It buys after intraday weakness, and much of the next-day gain
   follows down days. That needs to be controlled for (against the reversal baseline) before any gain is credited to
   the LSTM.
4. **The pre-close (3:40 PM) model has a small ceiling of value over next-open:** at most the overnight component of
   about 8 bp per signal before costs.
5. **Recommendation:** do not build the intraday model now. Two reasons: the measurable upside over next-open is small
   (point 4), and no historical intraday data is available to test it (G2). Run the planned PIT S&P 500 study with
   `StrategyParams.pit()` (next-open fills, member mask, spread, impact and fee costs) and the reversal baseline. If a
   pre-close model is still wanted later, start forward recording (15:40 snapshots plus official closes for PIT members)
   under its own preregistration, with next-open as the comparator.

## Limitations
- **Legacy Opens:** 30 of 212 legacy tickers (11,550 of 97,454 rows) have a raw Alpha Vantage close that differs from the
  forecast Close by a near-constant ratio all period, so they are on a different price basis. Their Opens were rejected
  by the preregistered 0.5% rule. Legacy B and the legacy overnight / next-session statistics exclude those tickers.
  The walk-forward set has zero mismatches.
- **Prices are unadjusted.** No event crossed the 0.4 split flag.
- **Survivorship:** the A-B universe has survivorship bias (see the walk-forward results). The event statistics are
  relative to the same universe.
- **Costs:** a flat 20 bps per side. No spread or impact model. Overnight and next-session splits are gross.
