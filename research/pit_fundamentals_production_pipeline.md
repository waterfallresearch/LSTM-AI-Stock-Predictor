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

## Bulk-export checkpoint, 2026-11-22

The WRDS form accepts up to 4,096 characters in its company-code field. The 674 GVKEY candidate set was split into two 337-code batches. Gzipped CSV exports can be saved directly through the browser download action. Validate the actual point-date range in each downloaded file because one browser request returned only February from an intended longer date range.

| WRDS query | Verified local result |
|---|---|
| 11939651 | 6,480 usable source rows across 24 GVKEYs, January–March 2015 |
| 11939657 | 31,310 usable source rows across 337 GVKEYs, January 2014 |
| 11939659 | 27,125 usable source rows across 294 GVKEYs, January 2014 |
| 11939663 | 28,280 usable source rows across 337 GVKEYs, February 2014 |
| 11939665 | 294,178 usable source rows across 300 GVKEYs, February–December 2014. There are 132 quarantined point-date keys with competing update records. |
| 11939666 | Submitted the complementary 337-code batch for March–December 2014. Pending verification. |
| 11939668 | 368,960 usable source rows across 337 GVKEYs, January–December 2015. |
| 11939670 | 330,862 usable source rows across 310 GVKEYs, January–December 2015. There are 29 quarantined point-date keys. |
| 11939656 | CRSP Apple reference export, with an unadjusted traded price and shares on January 28, 2016. Parsing preserved CRSP's thousand-share units for the downstream conversion. |

Files are local under `TrainingData/indicators_data/wrds/fundamentals_gate`. The parser supports WRDS gzip CSV output, preserves missing amount markers, and keeps a separate conflict ledger during preflight. CRSP daily exports can supply quotes directly while a separate names export is still required to establish the expected class roster. This is collection and parser evidence. The production coverage gate remains unrun. Twenty-one focused tests passed.

## Development data collection

- The March–December 2014 balance completed. The six development-period quarterly WRDS batches covered all three date windows from January 2016 to December 2024 and yielded 6,441,687 normalized point-date rows after filters and conflict quarantine. Further exports add WRDS year-to-date income, preferred capital, fiscal quarter, and fiscal year. Select one nonoverlapping set using `--snapshot-manifest` before preflight.
- CRSP daily, names, and delisting exports were saved locally. The names queries used all 681 issuer IDs from the roster-price extraction and required the historical record start date to be on or before December 31, 2024. This exposed 13 additional common share classes, whose quotes were fetched separately. The normalized sources include 66,832 quotes, 3,052 common-class spells, and 103 verified delisting dates. The frozen roster maps to 54,217 complete class-verified market caps. The 258 remaining rows stay in the denominator.
- CCM exports used historical CIK records intersected with dated LC/LU security links and clipped to the development cutoff. The resulting crosswalk has one candidate for 53,848 security-months and none for 627. A dated candidate still requires two original SEC asset anchors. The refreshed EDGAR cache contains Company Facts for 698 of 702 requested CIKs across the historical and earlier diagnostic sets.
- Claude reviewed the size-denominator and fiscal-period design. The fixed CRSP monthly size groups now use conservative bounds for unknown-size rows. Exact reporting dates remain the matching rule for this specification. A future dated fiscal normalization rule must run consistently across all eligible accessions without choosing mappings based on agreement with financial values.

The verified wide-export selection is stored locally as `snapshot_batches_wide.json`. It names WRDS queries 11939717, 11939718, 11939720, 11939721, 11939724, 11939725 and 11939726. Each file was independently checked for its requested start and end point dates and the four added fields. The last batch covers two GVKEYs found by the historical CCM crosswalk that were outside the old candidate list.

Run `python -m TrainingData.pit.fundamentals_receipts INPUT_DIRECTORY SNAPSHOT_MANIFEST` to generate machine-produced **candidate** context receipts. The generator requires a unique dated historical CIK and exact WRDS fiscal period, records the SEC source-file hashes, and retains both quarterly and nine-month Q3 net income when the durations agree. Preferred carrying value requires positive evidence from that accession, including an explicitly reported zero where present. Missing preferred evidence remains unresolved. Candidate files are separate from `verified_filing_contexts.parquet` and need independent review before production use.

Claude withheld full audit clearance and flagged multiple point dates per filing, reconciling receipts against EDGAR, incomplete rejection reasons, non-month-end fiscal dates, and bias in the size denominators when issuer cap is missing. The integration now uses accession-aware point-date selection, validates receipts against cached SEC facts, and records several previously silent rejection reasons. Exact fiscal-period matching remains frozen. Missing issuer size still needs independent size evidence or a reviewed subgroup treatment before a gate pass can be claimed. Eighteen focused tests passed.
