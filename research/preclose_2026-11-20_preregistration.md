# Pre-close (3:40 PM) execution test, reversal proxy: preregistration (2026-11-20)

Written **before** any intraday or 2025-2026 daily data is analysed. The intraday download had started but nothing had
been opened. Results go in `preclose_2026-11-20_results.md` / `.json`. Any change after results are seen is logged as
an amendment and counted as a trial.

## Why, and what it costs
- The latency study (`latency_2026-11-20_results.md`) found that the LSTM's signals buy stocks that lagged on the
  signal day. Most of the same-close advantage is earned in the next session (captured by a next-open fill); only
  about 8 bp is overnight.
- A pre-close order can only add value over next-open if the day-t information is already known by 3:40 PM.
- LSEG intraday history exists only from 2025-11-19, a rolling window of about one year. On 2026-11-20 the user chose
  to use that year for this test.
- **Cost:** the window 2025-11-19 → 2026-11-18 inside the reserved confirmation period is spent. The PIT study's single
  confirmation run shrinks to 2025-01-02 → 2025-11-18 (amendment 3 of `pit_nextopen_2026-11-20_preregistration.md`).
- No LSTM forecasts exist for this window, so this test uses a rule-based **reversal proxy**: the mechanism the LSTM's
  signals resemble. A retrained PIT LSTM is a later, separate test once the data layer is complete. The conclusion
  here applies to the mechanism, not to the LSTM.

## Data (frozen)
- **Universe:** each session t, the S&P 500 members (`membership_pit.csv`) with valid daily bars on the sessions each
  variant needs, and a 3:40 snapshot on t. All members are above $5.
- **Daily prices:** RAW from `prices_pit.parquet` via `pit_panel.load_pit(..., confirm=True)` with end 2026-11-18. The
  official close is the auction price used for market-on-close fills. Splits are applied through the panel's split
  factors so returns across a split are correct. Dividends are ignored (they are small over one session and affect the
  basket and the universe alike).
- **3:40 snapshot:**
  - From the 5-minute LSEG bars (`TrainingData/indicators_data/lseg/intraday/5min_20261120/`).
  - Bar labels are interval **start** times in naive UTC: the opening-cross volume falls in the 9:30 bar and the
    closing-cross volume in the 16:00 bar.
  - The snapshot price is `TRDPRC_1` (last trade) of the bar labelled **15:35 New York time**, which covers
    15:35-15:40. If it is missing, the last trade at or before 15:35 that session is used. If none exists after 15:00,
    the security is dropped for that day.
  - Times are converted from UTC with America/New_York, so daylight saving is handled.
  - Bid/ask from the same bar are recorded.
- **Survivorship:** LSEG has no intraday history for delisted RICs. Securities delisted inside the window (9 of 530)
  are missing on days without bars. Their count is reported.

## Signal
- `r_t^X = P_X / (C_{t-1} / F_t) - 1`, the move from the split-adjusted previous close to price X on day t.
  - X = the 3:40 snapshot for the pre-close signal;
  - X = the official close C_t for the post-close signal.
- **Basket:** the bottom decile of `r_t^X` among the day's eligible members (the day's losers), equal-weighted, long
  only, rebalanced every session.

## Variants (all one-session holds; all count as trials)

| Variant | Signal from | Entry | Exit | Implementable? |
|---|---|---|---|---|
| A | close t | close t | close t+1 | no (look-ahead reference) |
| **D** | **3:40 PM t** | **close t (market-on-close)** | **close t+1** | **yes** |
| B | close t | open t+1 | open t+2 | yes (daily-data alternative) |
| C | close t | close t+1 | close t+2 | yes |

## Return measure
- **Gross excess:** the basket's equal-weighted return over its holding interval, minus the equal-weighted return of
  the variant's eligible universe over the same interval. This removes market moves.
- **Net:** gross excess minus costs. Costs are half the trailing quoted spread at entry and at exit (the `pit_panel`
  spread rule) plus the SEC Section 31 rate on the exit notional (`fee_rates.csv`).
  - The same cost rule applies to all variants. Opening spreads are typically wider than closing spreads, so B's net
    is optimistic.
  - Impact is ignored and turnover is reported.

## Primary test (decides whether pre-close execution is worth building)
Daily series `D - B` (gross excess, same session t), Newey-West t with 5 lags. **"Pre-close adds value over next-open"**
only if all hold:
1. mean(D - B) > 0;
2. Newey-West t ≥ 2.0;
3. D's mean net excess > 0.

## Secondary (reported, not pass/fail)
- **Capture ratio:** (D - C) / (A - C), the share of the same-close advantage that a 3:40 signal keeps, with a 20-day
  block-bootstrap 95% CI (5,000 resamples, seed 20261120).
- **Signal agreement:** the daily Spearman correlation between the 3:40 and close signals, and the overlap of the two
  bottom-decile baskets.
- **Each variant on its own:** mean gross and net excess with Newey-West t; the long-short spread (bottom minus top
  decile); the top decile alone.
- **Monthly breakdown** of D - B.
- **Coverage:** sessions, securities per day, days without a snapshot, dropped securities.

## Trial accounting
N was 31. This study adds 4 configurations (A, B, C, D), so N = 35. The PIT next-open study's four configurations then
bring it to N = 39 (amendment 3 there).

## Known limitations
- **Power:** one year, about 248 sessions; the CIs will be wide.
- **Proxy:** this tests the reversal mechanism, not the LSTM itself.
- **Fills:** a market-on-close order must be entered by the exchange cutoff (NYSE 3:50 PM), which a 3:40 decision
  allows. Auction fills are assumed at the official close, with no auction impact.
- **Prices:** snapshot prices are last trades, not mid quotes.
