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

Run `python -m TrainingData.pit.fundamentals_receipts INPUT_DIRECTORY SNAPSHOT_MANIFEST NEW_OUTPUT_DIRECTORY` to generate machine-produced **candidate** context receipts. The generator requires a unique dated historical CIK and exact WRDS fiscal period, records the SEC source-file hashes, and retains both quarterly and nine-month Q3 net income when the durations agree. Preferred carrying value requires positive evidence from that accession, including an explicitly reported zero where present. Missing preferred evidence remains unresolved. Candidate files are separate from `verified_filing_contexts.parquet`. Before preflight, independent review must bind the candidate-manifest and reviewed-context hashes in `reviewed_context_manifest.json`. Preflight also rechecks the SEC source hashes stored in the receipts.

The first run produced 25,145 candidate receipt rows across 20,106 accessions and 680 CIKs. It reported 3,621 missing or conflicting exact fiscal labels, 3,151 missing or ambiguous historical issuer mappings, and four missing SEC sources. The SEC cached carrying-value concept supplied zero eligible accession matches. The preferred-stock par or stated value concept cannot supply a carrying amount. Independently reported zero preferred shares or direct filing context will be needed to verify absence. No feature coverage was measured. [SEC-filed taxonomy definition](https://www.sec.gov/Archives/edgar/data/1471727/000114036120002020/R75.htm)

Candidate Parquet SHA-256 `4cbb83d6a31d04253c7b1a81ecf7d435fdc0e0a07a3f64b6373ae93bff01d2ae`. Twenty-five focused tests passed.

The preferred-stock verifier now accepts a unique carrying amount or an explicit zero outstanding-share fact without contradictory issued shares or preferred value, from the same accession and period. It still requires independently matching WRDS common equity. A separate SEC sidecar collection was started for the 680 candidate issuers. This leaves the initial Company Facts cache and its hashes intact. Twenty-six focused tests passed after adding the zero-share and contradictory-evidence checks.

## Source preflight and independent audit

The preferred-share rerun produced 4,621 accessions with explicit zero-share evidence. Claude cleared the exact candidate context hashes for source preflight after four SEC filing-index acceptance times agreed to the second with the cached timestamps converted from UTC to Eastern time. The reviewed candidate manifest SHA-256 is `061afa4becc8c7273915b88c9c52e37992a2eb1ac718fc310af93d53c49154f7`. The context Parquet SHA-256 is `c473b149338b74ecd8b88e816dfeb4175e71b606746a466aae5e90a3705d5573`. Supply the reviewed manifest path with `--candidate-manifest` to preserve earlier evidence.

An independent decimal recomputation of 53,782 distinct prior-session issuer market caps found zero differences above 1%. The largest floating-point difference was approximately 2.22e-16 relative. The local audit Parquet SHA-256 is `5ce63c622394921e4aab4e777005b538a9d6c4ba729fb726850b887278a08964`.

The SEC quarterly statement archive is reachable through the browser. The 2022 Q3 pilot supplies 484 matching accessions and 5,298 whole-entity standard-taxonomy numeric rows. The archive's acceptance times are minute-resolution Eastern times. Use the original EDGAR index for the exact acceptance second. The pilot is independent audit evidence and has not been added to the feature contexts. [SEC Financial Statement Data Sets](https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets)

Use `python -m TrainingData.pit.fundamentals_audit PREFLIGHT_DIRECTORY NEW_AUDIT_DIRECTORY --freeze` to freeze the accession-level 120/40 review sample. The archive reader can extract the matching SEC submissions, facts, and statement labels for the sample without retaining any confirmation-period rows. The audit finalizer requires the same preflight and panel hashes, the frozen sample hash on each evidence receipt, and the independent CRSP market-cap evidence file. Coverage still requires a separate Claude clearance.

The cleared source preflight completed with 54,475 frozen security-months, 50,421 admitted historical issuer rows, and 20,145 reconciled vendor vintage rows across 19,717 accessions. Its manifest SHA-256 is `56d12b861263a63c4d791ad9ee3435567fe34aa895d871358dce02ac7045f6ef`. The 120 accepted and 40 rejected review accessions are frozen under sample SHA-256 `10776346ca2ab70aaa627f00b1f1667ba6cc4e34144494ea03b43bb771fee977`. The mandatory references include an original annual filing, a quarterly filing from a later-delisted issuer, and a quarterly amendment. Coverage was not computed during preflight or sample selection.

Claude withheld full audit clearance and flagged multiple point dates per filing, reconciling receipts against EDGAR, incomplete rejection reasons, non-month-end fiscal dates, and bias in the size denominators when issuer cap is missing. The integration now uses accession-aware point-date selection, validates receipts against cached SEC facts, and records several previously silent rejection reasons. Exact fiscal-period matching remains frozen. Missing issuer size still needs independent size evidence or a reviewed subgroup treatment before a gate pass can be claimed. Eighteen focused tests passed.
