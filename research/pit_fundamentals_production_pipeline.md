# Fundamentals production assembly

The assembly reads local WRDS browser exports and independently checked EDGAR receipts. The preflight writes dated issuer and market-cap inputs, reconciled filing vintages, quarantines, and an input and code hash manifest. It neither evaluates coverage nor reads strategy returns or labels.

## Inputs

| Local input | Contract |
|---|---|
| `roster.csv` | Original frozen, byte-identical roster |
| `snapshot_*.htm` or `snapshot_*.csv` | WRDS Snapshot Point in Time Quarterly export. Use all relevant daily point dates, including history before 2016. Include GVKEY, data and point dates, fiscal year-end month, total assets, common equity, net income, consolidation, format and currency. An optional normalized `niy` field supplies the WRDS nine-month income check. |
| `edgar_metadata/<CIK>.csv`, `edgar_facts/<CIK>.json` | Cutoff-filtered SEC caches from the prior EDGAR source modules |
| `verified_filing_contexts.parquet` | Independently checked accession receipts. Requires `gvkey, cik, accession, form, period, accepted_at, fiscal_year, fiscal_quarter, fiscal_year_end, currency, basis, consolidated, assets, parent_equity, preferred, preferred_verified, income, income_type, income_start, receipt`. Amounts are USD. Income types are `quarter`, `annual`, or `nine_months`. A receipt references the independent filing-context review. Preferred stock requires separate positive evidence or verified absence. Missing facts stay missing. |
| `links.parquet` | Dated CCM candidates with `signal, permno, gvkey, cik, start, stop`. Normalize issuer keys as strings and clip open intervals upstream. |
| `listing.parquet` | Independently verified expected common classes with `permco, permno, start, stop`. Include all applicable classes, including those outside the S&P 500 roster. |
| `quotes.parquet` | `session, permno, permco, price, shrout`. Price is the verified unadjusted close in dollars. CRSP shares outstanding are in thousands and converted once inside the pipeline. |
| `delistings.parquet` | One verified development-period `delist_date` per `permno`. Do not include 2025 or later outcomes. |

Run the preflight with `python -m TrainingData.pit.fundamentals_pipeline INPUT_DIRECTORY NEW_OUTPUT_DIRECTORY --preflight`. After Claude clears that exact manifest, use the preflight directory as the input and supply `--review-receipt PATH`. The receipt records `reviewer` (Claude), `decision` (clear), and the exact `preflight_sha256`. The runner checks the artifact and code hashes before emitting the panel and coverage. The 160-case independent acceptance audit remains a separate step.

## Current evidence

The parser loaded all 552 rows of the actual Repligen WRDS browser export. It preserved original and amended income point dates and the unreconciled intermediate observation. The integration fixture reproduces both verified effective dates, excludes the middle value, applies the prior-session rule, and leaves capitalization missing when an expected share class has no valid close.

The reference export is local and Git-ignored. Its SHA-256 is `13437c16baa1530b0060c47816c11125be30e23707e519896781dd8bcf2e05e6`. The bulk WRDS and CRSP files and independently reviewed filing-context receipts are still needed to exercise the full live pipeline. There has been no coverage run or strategy trial. The confirmation window remains sealed. [WRDS reference query](https://wrds-www.wharton.upenn.edu/query-manager/query/11939595/)

A live reference reconciliation joined the WRDS export to cutoff-filtered SEC evidence. Original net income first became usable July 31, 2024, and the amendment first became usable November 29. The unmatched intermediate value produced no verified replacement. Book equity was left missing in this live check because the preferred-stock context was outside the reference audit.

Claude withheld full audit clearance and flagged multiple point dates per filing, reconciling receipts against EDGAR, incomplete rejection reasons, non-month-end fiscal dates, and bias in the size denominators when issuer cap is missing. The integration now uses accession-aware point-date selection, validates receipts against cached SEC facts, and records several previously silent rejection reasons. Exact fiscal-period matching remains frozen. Missing issuer size still needs independent size evidence or a reviewed subgroup treatment before a gate pass can be claimed. Eighteen focused tests passed.
