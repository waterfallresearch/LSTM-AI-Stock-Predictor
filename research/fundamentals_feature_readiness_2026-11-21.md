# Fundamentals feature-readiness follow-up

Read-only pilot run in parallel with the breadth implementation. Tested the same three SEC-linked issuer quarters with LSEG Workspace and WRDS Compustat Snapshot. USD millions unless noted. No model fitting and no reads of reserved outcomes.

| Issuer quarter | Original assets | Original quarterly net income | Dual-vendor outcome |
|---|---:|---:|---|
| Apple, December 2023 | 353514.000 | 33916.000 | Both match the SEC accession, with December 30 issuer close and December 31 Compustat period mapping. |
| Repligen, June 2024 | 2861.924 | 3.321 | WRDS original and SEC match. LSEG returned amended net income 5.713 with a July calculation date. WRDS first provided the SEC-matching amendment in its November 28 snapshot. |
| Twitter, June 2022 | 13579.287 | -270.007 | Both match the original 10-Q. Keep the filing-level availability date for fields verified only in that 10-Q. |

WRDS dated link examples (GVKEY to PERMNO) were Apple 001690 to 14593, Repligen 012181 to 10200, and Twitter 018872 to 14295. The Twitter link ends October 31, 2022 and the last executable bar was October 27. CRSP daily records expose a security-level CUSIP, price and shares. These keys must be tested as of each signal before computing market capitalization. Quarter-end equity and public report dates are not substitutes for known security-level price and share dates.

Assets and net income can seed a later profitability and asset-growth pilot. Respect the filed consolidated basis, filed quarter duration, and snapshot arrival date. The original Apple operating cash flow and capital expenditure matched the filing ($39,895M and $2,392M). Repligen cash flow and capex are null on the first snapshot. Its later capxy was 15.773 while the SEC property, plant and equipment payments tag was 13.154 for the first half. Leave this mapping unapproved until the investment categories are reconciled. WRDS YTD fields cannot be treated as single quarters without validated same-fiscal-year differences. Do not use these pilot cases to infer full-universe coverage or retrospectively promote a feature.

The prior LSEG earnings pilot supports same-period matching on selected events. Historical actual activation remains unverified, and the visible WRDS EPS samples lack usable development-window coverage. An earnings or fundamentals feature experiment remains conditional on coverage and vintage acceptance.

SEC accession numbers audited: Apple 0000320193-24-000006, Repligen 0000950170-24-087981 and 0000950170-24-127845, Twitter 0001418091-22-000147. The underlying SEC Company Facts API and the two vendor APIs were queried read-only. This evidence supplements the dual-source revenue pilot and does not enter the frozen breadth experiment.

## Preliminary universe coverage

A read-only WRDS aggregation restricted industrial-format, standardized, consolidated USD quarters to 2016–2024, selected each company/period's earliest snapshot before 2025, and linked fiscal period ends through dated primary LC/LU CCM rows to historical CRSP S&P 500 membership. Among 17,487 returned company-quarters, the first snapshot contained assets in 90.6%, net income in 99.5%, book equity in 88.8%, YTD operating cash flow in 72.2% and YTD capex in 69.8%. These percentages are conditional on a returned and linked snapshot. They do not measure daily feature availability or the share of all eligible S&P 500 members with usable observations. Period-end membership was used for this diagnostic only. Missing fields remain missing. The production gate still needs a dated security-level join, signal-session coverage, consecutive comparable period pairs and resolution of accounting discrepancies.

Claude reviewed the metric pilot and agreed to keep scoring gated. The Repligen amendment first matched WRDS on November 28, 2024. The SEC filing and WRDS snapshot date provide distinct provenance.
