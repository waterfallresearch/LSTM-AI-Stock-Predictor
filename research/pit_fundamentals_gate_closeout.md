# Point-in-time fundamentals gate

**Decision — blocked on source access.** Claude reviewed the source check and signed off on the blocked status. The full coverage audit has no clearance. The 49-trial strategy ledger and the sealed 2025 confirmation are intact.

## Evidence

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
