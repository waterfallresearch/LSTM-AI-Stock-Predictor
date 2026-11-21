# EDGAR source validation

This diagnostic uses the frozen 2016–2024 CRSP S&P 500 roster of 54,475 security-months. It measures public periodic filing availability and corroboration with dated Compustat Snapshot periods. The fundamentals feature gate, its acceptance thresholds, and the 49-trial strategy ledger are separate.

## Results

| Check | Security-months | Coverage |
|---|---:|---:|
| Unique candidate after the dated primary CCM join | 53,813 | 98.78% |
| Recent original 10-Q or 10-K available from EDGAR | 53,037 | 97.36% |
| Recent original filing with an exact period and eligible WRDS vintage | 45,410 | 83.36% |

All 674 candidate CIKs responded. The filtered metadata contains 26,415 filing records, including amendments before the cutoff. No candidate survived the dated join for 662 security-months. The strict filing-period measure ranged from 79.83% in 2016 to 86.73% in 2023. Rates use the frozen roster denominator. An independent read of the saved Parquet reproduced the roster, counts, and timing checks. The protected price, return, and confirmation artifacts remained sealed.

The result supports using EDGAR as the filing evidence source. Full historical CIK provenance and compatible as-filed values still need verification before admitting feature rows. Claude reviewed the diagnostic and flagged failed downloads, cache provenance, and timestamp handling. The run separated source failures, recorded per-file hashes, and checked four timestamps against the SEC indexes. This is a source diagnostic with no strategy scoring.

## Identity and timing

Intersect the effective dates of primary LC/LU CCM links and CCM lookup rows for each PERMNO and GVKEY. Treat the lookup CIK as a candidate. Its presence in a dated link row does not independently prove the CIK's own effective dates. Preserve unlinked and ambiguous security-months in the denominator.

In a seeded sample of 36 distinct GVKEY–CIK pairs, 33 matched SEC assets and equity to WRDS within $500 for at least two distinct filing periods. Three had no two-field match. Visa and Newfield had no values under the plain StockholdersEquity tag in the selected window. Citizens had both tags and remains unreconciled on the numeric test. The WRDS and EDGAR names agree for Visa and Citizens. A dated SEC disclosure confirms Newfield was renamed Ovintiv Exploration before a later merger. [Ovintiv 2021 8-K](https://www.sec.gov/Archives/edgar/data/1792580/000119312521137143/d251384d8k.htm)

Four reference timestamps from the API matched the filing-index Eastern times after conversion from UTC, including a winter filing, summer filings, and an amendment. [Apple 10-Q](https://www.sec.gov/Archives/edgar/data/320193/000032019324000006/0000320193-24-000006-index.htm) · [Twitter 10-Q](https://www.sec.gov/Archives/edgar/data/1418091/000141809122000147/0001418091-22-000147-index.htm) · [Repligen original](https://www.sec.gov/Archives/edgar/data/730272/000095017024087981/0000950170-24-087981-index-headers.html) · [Repligen amendment](https://www.sec.gov/Archives/edgar/data/730272/000095017024127845/0000950170-24-127845-index.htm)

For each security-month, use original 10-Q and 10-K acceptance times before the prior session opens and a reporting period within the previous 180 days. The stricter measure also requires the exact SEC reporting period to match the WRDS period and an independently dated snapshot to have arrived before that session. Exact matching can miss 52/53-week reporting calendars. These counts do not reconcile amendment chains, accounting definitions, book-to-market, or Q4 derivation. Source-request errors are reported separately from missing filings. [SEC API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)

Run `python -m TrainingData.pit.edgar_coverage` with the WRDS username environment variable and the saved database login. The filtered metadata, provenance manifest, sample evidence, and security-level output are stored under the ignored WRDS fundamentals directory. The independent numeric sample uses seed 20261121. Its local JSON SHA-256 is `91d642063c33b33053cf9ea7f96a63b55b107b32582217453c95ac3fa42f5654`.

- Metadata manifest SHA-256 `ac313ca147b668fa1ccc1fb6ce8a48d7d76ae9b5fac8e2410b4114030deffc9b`
- Coverage Parquet SHA-256 `6a3b52da1327e5be23de9cbcb1ab91fa0e317e5a68e301ee6fac251c89fc7ec0`
- Focused tests `python -m pytest -q --disable-warnings tests/test_edgar_coverage.py tests/test_pit_fundamentals_gate.py tests/test_dual_fundamentals.py` passed 9 checks.
