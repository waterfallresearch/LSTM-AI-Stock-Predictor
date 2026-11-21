# Fundamentals implementation checkpoint

The gate remains open and unscored. The local roster, filing metadata, feature components, and audit rules are available. A vendor-backed production panel and acceptance review remain outstanding.

| Plan item | Evidence |
|---|---|
| Development universe | Frozen CRSP S&P 500 roster, 54,475 security-months across 108 month-ends. The source run reproduced its hash and preserved the full denominator. |
| Historical filing source | EDGAR original filings cover 53,037 security-months before fiscal-period matching. The strict EDGAR and WRDS period-and-date check covers 45,410. The expanded, cutoff-filtered Company Facts cache covers 672 of 674 candidate CIKs, with two HTTP 404 responses. |
| Issuer corroboration | Added exact-dollar original-assets matches and a two-anchor admission rule requiring distinct periods inside the same historical link window and both filing vintages known by the prior session. The live universe reconciliation did not run because WRDS PostgreSQL timed out. |
| Feature and audit components | Added exact accession selection, same-context Q4 subtraction, expected PERMNO share-class matching, causal amendment selection, feature math, subgroup calculations, a seeded sample selector, and the frozen decision floors. Verified on fixtures. |
| Production inputs and review | Still required: independently verify accession-level income and parent-common equity context and preferred treatment, connect the live Q4 and CRSP class/delisting producers, compute the panel after pre-run clearance, and complete the 120 accepted and 40 rejected filing reviews plus independent cap checks. |

WRDS PostgreSQL timed out on two direct connection attempts before the probe could execute. The TCP port accepted a separate check, but the SQL session still failed on retry. This is a database connection problem observed during the run. The licensed historical extracts and row-level files remain local.

Claude reviewed the source amendment and engine and signed off on the blocked disposition. The review prompted stricter rules for issuer anchors, amendment forms, stale periods, missing lineage, immediately preceding sessions, and matching actual share-class identifiers. After Claude identified missing guard tests, Codex added assertions for stale filings, incorrect prior and market-cap sessions, premature availability, and annual income in a quarterly slot. Sixteen focused tests passed on the amended code. The feature components were exercised on test fixtures and the EDGAR download ran on the full candidate list. The production sources and independent audit have no clearance. No returns, labels, or confirmation artifacts were used. Strategy trials remain 49.

- Frozen roster SHA-256 `00322c50661b320f9db84b21b9e6d14fc75f174126030c6de727aa6c902adf56`
- EDGAR Company Facts manifest SHA-256 `1abdd5dfa6d0e60a8ef513015f0c46632307afd67107d9a04208557449b63ed3`
- Source amendment commit `2682b05`
- Source and feature code commit `216e8b9`
- Review fixes and additional assertions commit `46e3dd8`
