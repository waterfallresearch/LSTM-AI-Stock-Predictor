# Point-in-time fundamentals validation

## Apple earnings pair

The LSEG Workspace API returned USD comparable EPS actual of 2.18 for AAPL.O, with vendor period end 2023-12-31 and event date 2024-02-01 16:30 (time zone unverified). The latest strictly earlier exchange-session consensus in the sample was 2.09812 USD on 2024-01-31, for the same vendor period. The difference is 0.08188 USD per share (3.90% of consensus). The February 1 FQ1 snapshot already pointed to March 2024 and is ineligible.

Apple identifies this as fiscal Q1 2024 ending 2023-12-30 and reports diluted EPS of 2.18. Keep the vendor period key for the within-I/B/E/S join and preserve the issuer period separately. LSEG documents comparable actuals aligned to consensus; per-row split basis and historical actual activation remain to be verified before training.

- https://www.apple.com/newsroom/2024/02/apple-reports-first-quarter-results/
- https://www.lseg.com/en/data-catalogue/company-data/ibes-estimates/actuals

## Repligen restatement check

For 2024 Q2, the RGEN.O period-history query returned revenue of 158,839,000 and operating income of 5,469,000 with revenue Calc Date 2024-07-30. The original 10-Q reported 154,073,000 and 1,487,000. The amended 10-Q/A dated 2024-11-18 reported the amounts returned by LSEG. SEC Company Facts independently returned both operating income values with separate accession numbers. The tested LSEG fields backfill amended values against the original calculation date and fail the point-in-time check.

- Original 10-Q accession 0000950170-24-087981
- Amended 10-Q/A accession 0000950170-24-127845
- https://www.sec.gov/Archives/edgar/data/730272/000095017024127845/rgen-20240630.htm

No training inputs were changed. These are development checks. Next checks are dated security identity, EPS basis and activation metadata across a broader pilot, and accession-based financial statement vintages with availability gates.

## Expanded live pilot

The Workspace TR.ISIN results agree with the local dated security master for all four names. The LSEG period end and currency agreed on each actual and estimate pair. The calculation dates below were independently checked against the previous XNYS session.

| Security (ISIN) | Event date | I/B/E/S period end | Prior session | Actual USD | Consensus USD | Difference vs consensus |
|---|---|---|---|---:|---:|---:|
| Apple (US0378331005) | 2024-02-01 | 2023-12-31 | 2024-01-31 | 2.18 | 2.09812 | +3.90% |
| Microsoft (US5949181045) | 2024-01-30 | 2023-12-31 | 2024-01-29 | 2.93 | 2.78152 | +5.34% |
| JPMorgan (US46625H1005) | 2024-01-12 | 2023-12-31 | 2024-01-11 | 3.04 | 3.32242 | -8.50% |
| Yahoo/Altaba (US0213461017) | 2017-04-18 | 2017-03-31 | 2017-04-17 | 0.18 | 0.13906 | +29.44% |

The queried TR.EPSActValue.activationdate property did not return a column. TR.EPSActValue.splitfactor and TR.EPSMean.splitfactor did not return populated factors. These pairs establish matching keys and daily precedence, while row-level basis and actual vintage still require evidence.

SEC Submissions confirmed accession 0000950170-24-087981 was accepted at 2024-07-30T21:04:52Z and 0000950170-24-127845 at 2024-11-18T17:08:36Z. The two observations must remain separate. Use accession plus concept, period bounds and currency as source keys and a conservative availability date after SEC acceptance when dissemination time is unknown.

## I/B/E/S surprise cross-check

Queried TR.EPSActSurprise together with TR.EPSActValue, its event date and period end for the four pilot names, using Frq=FQ and Period=FQ0. Vendor percentages for Apple (+3.903%), Microsoft (+5.338%) and JPMorgan (-8.500%) reproduce the previous-session calculation at the vendor's displayed precision. This gives direct numerical evidence of comparable EPS basis for these observations. It does not establish original I/B/E/S activation or validate split-spanning events.

Yahoo/Altaba's vendor surprise was +29.936%, versus +29.4405% calculated from the prior session. The implied vendor comparator is about 0.13853, versus 0.13906 on April 17. Both TR.EPSMean and TR.EPSMeanEstimate return 0.13906 on April 17. On April 18 both roll to the June period. Keep this discrepancy open because the vendor benchmark can reflect a different snapshot and row-level basis metadata is missing.

- https://developers.lseg.com/content/dam/devportal/api-families/thomson-reuters-knowledge-direct-trkd/thomson-reuters-knowledge-direct-api/quick-start/trkd_api_developers_guide.pdf

## Repligen availability replay

Used the exchange session strictly after the SEC acceptance day in America/New_York as a conservative date-only availability policy. The filing-based values are absent July 30, use the original revenue and operating income (154,073,000 and 1,487,000) from July 31 through November 18, and switch to the amendment (158,839,000 and 5,469,000) on November 19. This was checked with the XNYS calendar; it is a pilot replay, not yet a production join.

## Split-basis checks and validation decision

| Security | Announcement | Vendor fiscal period end | Prior XNYS snapshot | Issuer EPS at release | I/B/E/S actual USD | I/B/E/S mean USD | Calculated vs vendor surprise |
|---|---|---|---|---:|---:|---:|---|
| NVIDIA (US67066G1040) | 2024-05-22 | 2024-04-30 | 2024-05-21 | 6.12 non-GAAP diluted | 0.612 | 0.55874 | +9.532% vs +9.532% |
| Apple (US0378331005) | 2020-07-30 | 2020-06-30 | 2020-07-29 | 2.58 diluted | 0.645 | 0.51089 | +26.250% vs +26.251% |

The issuer releases confirm subsequent 10-for-1 and 4-for-1 splits. The actuals are divided by the respective factors and the prior-session means are on a compatible share scale, as shown by agreement with vendor surprise to 0.002 percentage points. Use scale-invariant surprise for these comparisons. The back-adjusted EPS levels are not the raw levels visible on the announcement date.

- https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-first-quarter-fiscal-2025
- https://www.apple.com/newsroom/2020/07/apple-reports-third-quarter-results/

Pilot verdict: five of six cases corroborate the matched EPS basis using the vendor surprise. Hold the Yahoo/Altaba discrepancy out of validated observations. Join on dated security identity, exact vendor fiscal period and currency, choose the strictly prior exchange-session snapshot, and exclude unknown or inconsistent EPS basis. The Workspace statements query fails point-in-time validation on the confirmed Repligen restatement. Use source filing versions gated by acceptance-derived availability for a future statements build. Original historical I/B/E/S activation and universe-wide coverage are unverified and no rows were added to model training.
