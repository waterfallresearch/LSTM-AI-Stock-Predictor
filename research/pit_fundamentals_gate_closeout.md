# Point-in-time fundamentals gate

**Decision — FAIL on coverage.** The EDGAR and WRDS route enabled a full measurement on the preregistered universe. All required coverage floors failed. Claude cleared this disposition and closure to predictive promotion after reviewing the arithmetic and decision logic from the reported evidence. The strategy ledger remains at 49 trials and the 2025 confirmation remains sealed.

## Full coverage measurement

| Measure | Observed | Required |
|---|---:|---:|
| Complete three-feature coverage | 6,898 / 54,475 (12.66%) | 80% |
| Annual coverage range | 6.34%–16.61% | 70% each year |
| Market-cap tercile conservative bounds | 13.18%, 13.43%, 11.02% | 60% each |
| Delisted within 12 months | 153 / 890 (17.19%) | 60% |

Profitability was available for 37,139 security-months, asset growth for 41,096, and book-to-market for 8,703. Verified inputs came from WRDS, so the coverage with and without LSEG is identical. The 6,037 observations without a complete 12-month delisting window remain in the overall denominator. The size bounds include all 258 observations with unknown size in each denominator. Monthly coverage and failure counts are saved in the local coverage JSON. There were 38,148 rows with incomplete inputs, 5,369 with stale filings, 4,054 with no verified filing, and six with an ambiguous vintage.

Book-to-market is the binding constraint. Its coverage caps achievable complete coverage at 15.98% overall, 12.66%–19.02% across years, 13.97%–17.29% across known-size terciles, and 22.02% for the observed delisting subgroup. The strict accession-level common equity and preferred-stock evidence requirement contributed to the gap. The 6,898 complete rows are ineligible for predictive work under this specification. Changing the evidence rule or adding a fallback would require a new preregistration.

An independent implementation reproduced each feature availability flag for every key using the same frozen inputs. A separate recount verified the frozen roster keys and the reported coverage from the saved panel. Independent Decimal arithmetic reaggregated 53,782 CRSP issuer-date caps using prior-session prices, shares, and expected common share classes, with maximum relative difference of 2.22e-16. That check verifies units and aggregation on the supplied CRSP inputs. Of the security-months with missing caps, six lacked a dated class mapping and 252 were mapped but lacked a usable issuer cap.

The frozen filing sample contains 120 accepted and 40 quarantined cases. The automated run cleared 119 accepted and corroborated 29 quarantined cases. Supplemental public filing checks explain the remaining flags, and Claude reviewed them as documented explanations. The original audit receipts retain their flags. The discrepancies include a conflicting fiscal-year label, two nonfinancial amendments, five annual amendments outside the frozen Q4 rule, three missing verified nine-month contexts, and one issuer using a different parent-income tag. These counts describe the stratified sample.

| Verified artifact | SHA-256 |
|---|---|
| Reviewed preflight | `56d12b861263a63c4d791ad9ee3435567fe34aa895d871358dce02ac7045f6ef` |
| Coverage JSON | `26ac088e3eaa379e44dd5d2aaf54a1e0a8982f3d037e4bf138bf1a3d69c60f4b` |
| Panel | `6a64f585c16b22cea5a1c2cb3cd84df03826554fb4ffea4c7a243a81b5267e47` |
| Independent coverage recount | `03ce34b17ab1d4d217c25c478fa935cceda0c0cf8cd264b7cdde196f79194d79` |
| Frozen filing sample | `10776346ca2ab70aaa627f00b1f1667ba6cc4e34144494ea03b43bb771fee977` |
| Supplemental evidence manifest | `aa3e872942818c7e013109a75955c2b711a9588742fae1e66d6e0f31edc7846b` |
| Independent CRSP cap audit | `5ce63c622394921e4aab4e777005b538a9d6c4ba729fb726850b887278a08964` |

## Earlier source-access checkpoint

- The dated CRSP S&P 500 roster contains 54,475 unique security-months across 108 XNYS month-ends in 2016–2024, with 503–506 securities per month. An independent pass over the saved CSV reproduced the counts and hash. The roster is the security-level denominator, including historical members that later delisted.
- The CCM lookup returned one candidate issuer link on 54,374 security-months, none on 41, and competing candidates on 60. A unique candidate still requires dated issuer verification. These counts measure link candidates only. Complete signal-date fundamentals coverage remains unmeasured.
- Live WRDS probes returned the Twitter reference CCM, Compustat Snapshot, and CRSP daily records. Both the dated SEC issuer-link view and filing-acceptance view returned SQLSTATE 42501. The public EDGAR submissions endpoint confirmed Twitter’s June 2022 10-Q was accession 0001418091-22-000147, accepted July 26 at 16:32:11 Eastern. The other accession, 0001418091-22-000143, was the earlier earnings 8-K. The local HTTP requests for the official historical bulk ZIP and archive header returned 403. [Twitter 10-Q](https://www.sec.gov/Archives/edgar/data/1418091/000141809122000147/0001418091-22-000147-index.htm) · [Twitter earnings 8-K](https://www.sec.gov/Archives/edgar/data/1418091/000141809122000143/0001418091-22-000143-index.htm) · [SEC bulk data](https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets)
- Eight focused tests passed, including the prior pilot tests. This verifies source-stage behavior, including calendar cutoffs, frozen membership, and ambiguous links. The production value joins, feature calculations, independent market-cap audit, and stratified filing review are outstanding.

Claude withheld clearance because the dated filing path and production join were incomplete. The final review reconciled aggregate counts and accepted the disposition based on Codex’s evidence. Restoring WRDS SEC access or freezing and validating an EDGAR-direct source amendment would permit another source review. Preserve the frozen roster and the registered coverage thresholds on either route.

## Reproduction

With the WRDS username configured and credentials supplied through the local database client, run `python -m TrainingData.pit.fundamentals_gate`. Run `python -m pytest -q tests/test_pit_fundamentals_gate.py tests/test_dual_fundamentals.py` for the focused checks. Row-level artifacts are local under `TrainingData/indicators_data/wrds/fundamentals_gate`.

| Artifact | SHA-256 |
|---|---|
| Frozen CRSP roster | `00322c50661b320f9db84b21b9e6d14fc75f174126030c6de727aa6c902adf56` |
| Source probe JSON | `554e7d62bc13ec722cf79581d2bc3c2678e3123281c23875e18bdd79e5bb723` |
| EDGAR reference extract | `dc2c340f15e4afb7c63265764bb49ba0e1d2e476f2329991d666a8b63b9c8452` |
| Source code | Local commit `7ecaa31` |
| Preregistration | Local commit `a0706a4` |
