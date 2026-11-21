# Pre-close (3:40 PM) execution test, reversal proxy: results (2026-11-21)

Preregistration: `preclose_2026-11-20_preregistration.md`. Raw output: `preclose_2026-11-20_results.json`. Run once,
with `preclose_proxy.py --boot 5000`. Trial count after this study: **N = 35**.

## Verdict: pre-close execution does NOT add value over next-open (primary rule fails on all three conditions)

| Primary condition | Result | Pass |
|---|---|---|
| 1. mean(D − B) > 0 | **−8.6 bp** per day (248 sessions) | no |
| 2. Newey-West t ≥ 2.0 | t = **−1.30** | no |
| 3. D mean net excess > 0 | **−4.8 bp** per day | no |

Building a 3:40 PM signal with market-on-close execution is **not justified** by this evidence. The PIT next-open
design (`pit_nextopen_2026-11-20_preregistration.md`) remains the execution model.

## Each variant (bottom decile of the day's losers, equal weight, excess vs the eligible universe; bp per day)

| Variant | Signal → entry → exit | Gross | NW t | Net | Long−short (gross) | Top decile (gross) |
|---|---|---|---|---|---|---|
| A (look-ahead reference) | close t → close t → close t+1 | −1.9 | −0.29 | −5.4 | −7.8 | +5.9 |
| **D (3:40 PM, MOC)** | **3:40 t → close t → close t+1** | **−1.1** | **−0.17** | **−4.8** | −5.3 | +4.2 |
| B (next open) | close t → open t+1 → open t+2 | +8.1 | 1.17 | +4.5 | +9.3 | −1.3 |
| C (next close) | close t → close t+1 → close t+2 | +9.8 | 1.46 | +6.3 | +11.2 | −1.4 |

About 50 names per basket out of about 502 eligible members per day. Net costs are half the trailing quoted spread at
entry and at exit, plus the SEC fee on exit, about 3.6 bp per round trip.

Annualized Sharpe of daily net excess, used in the trial pool: A −0.66, B 0.57, C 0.77, D −0.59.

## What it means
- **The one-day reversal was not there in 2025-26 when entering at the signal day's close.** A, which uses perfect
  close-t information and is not implementable, is itself negative (−1.9 bp gross). That is the opposite of the
  latency study's 2016-2023 finding, where same-close entry earned about 27.6 bp more than next-close at signal level.
  - In this window the losers kept falling for one more day. A positive drift appears only from the next session on,
    in B (+8.1) and C (+9.8), but neither is significant (t 1.2 and 1.5).
- **A 3:40 signal captures almost the whole same-close behaviour.** The Spearman correlation between the 3:40 and
  close signals averages 0.94, and the baskets overlap by 79%. D and A are nearly identical (−1.1 vs −1.9 bp), so the
  information is mostly known by 3:40. In this window, though, that information was not worth trading at the close.
- **The capture ratio is not informative.** Its denominator, A − C, is negative this year (−11.7 bp). The point
  estimate of 0.92 has a 95% CI of [−0.90, 2.32], so it should not be read as "92% captured".
- **D − B by month, in bp:** positive in 6 of 13 months. July 2026 was the worst at −56, April the best at +30. No
  stable sign.

## Coverage
- 251 sessions in the window. 248 have all four variants; the first and last sessions lack t+1/t+2 bars.
- 530 of 530 securities have bars. A repair pass on 2026-11-21 re-fetched 66 windows for 17 securities that had timed
  out, including 3 that had been saved empty (HUBB, HUM, JBHT). The repair log is under `manifest.json`→`repair`.
- Members with a 3:40 snapshot: 500.1 of 503.0 per day.
- Snapshot bar used: 15:35 for 98.9% of rows, 15:30 for 0.8%, and earlier (down to 15:00) for 0.1%.
- **Survivorship:** no securities lack bars. LSEG kept intraday history for names delisted inside the window, so the
  limitation feared in the preregistration did not occur.

## Deviations and fixes (mechanical, before any number was seen)
- Two code fixes were made before results existed:
  - the window mask was broadcast across columns, fixing a crash before any computation;
  - `nw_stat` now also reports an annualized Sharpe, needed for the trial pool.
- No statistic, variant or cost was changed.

## Limitations
- One year of data (248 sessions). The CIs are wide: a true D − B of ±10 bp could not be ruled out.
- This tests the reversal mechanism, not the LSTM. A retrained PIT LSTM pre-close test would need its own
  preregistration. Given this result and the PIT study's outcome, it is low priority.
- Auction fills are assumed at the official close with no auction impact. Snapshot prices are last trades.
