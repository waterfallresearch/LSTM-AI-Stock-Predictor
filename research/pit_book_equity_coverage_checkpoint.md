# Book-equity coverage study checkpoint

The saved baseline contains 8,703 security-months with book-to-market. Of the 54,475 frozen roster rows, 44,829 have both a selected accession and a usable cap. Holding the filing selection fixed, this is an 82.29% theoretical ceiling for book-to-market alone. The corresponding ceiling for all three original features is 33,788 rows (62.02%) because the other two features also have missing inputs.

The frozen fresh screen excludes the prior 160 audit IDs. The candidate frame contains 35,438 missing security-months tied to accessions without verified preferred treatment and 652 tied to accessions already verified for preferred treatment. The initial 20-accession screening draw is for evidence-method development. The acceptance sample will be separately frozen.

In the first four filings, three expressly reported no preferred shares issued. Two of those cases had dated WRDS balances consistent with the reported parent equity and assets, yielding six candidate security-month recoveries under the existing timing rules. The third had no exact qualifying WRDS match. The fourth did not establish an explicit preferred balance in the screen. Candidate recoveries still require applicable accounting and evidence review before admission. [Boeing 10-K](https://www.sec.gov/Archives/edgar/data/12927/000001292716000099/a201512dec3110k.htm) · [Franklin Resources 10-Q](https://www.sec.gov/Archives/edgar/data/38777/000003877717000010/form10q12312016.htm) · [Marsh & McLennan 10-K](https://www.sec.gov/Archives/edgar/data/62709/000006270917000008/mmc1231201610k.htm)

The separate amendment frame contains 314 pairs. Both preferred-stock balances were verified for five pairs, and only one of those changed common equity. Its original WRDS value was available before the amendment, and the changed value was absent both before and after the amendment in the local extract. This case does not demonstrate timely adoption of the revised amount.

All 20 screening documents were subsequently retrieved and their response hashes recorded in the local evidence bundle, SHA-256 `5d7241de3aeecc3046234381a907cca635394df0b8049c14fffad6ec68d80831`. Five filings have clear text candidates for zero parent preferred shares. Two others show nonzero preferred claims requiring accounting review. News Corp's filing describes a redeemable obligation issued by a subsidiary, illustrating why either a generic keyword or a consolidated balance alone is insufficient to establish the parent-common adjustment. [News Corp 10-K](https://www.sec.gov/Archives/edgar/data/1564708/000119312518249117/d603651d10k.htm)

## Structured zero-issuance route

Accession-specific SEC facts produced 2,190 candidate filings. Exact dated matches to WRDS assets and common equity provided 1,213 issuer filing candidates and 3,534 incremental security-months before final review. The fresh stratified sample included 120 candidate recoveries and 40 candidate rejections. It excluded the original 160-case audit and the 20-case screen. All 160 sampled accessions reconciled against original SEC instances and SEC index acceptance timestamps. Nine rejected instances lacked the comparable parent-equity fact. One original instance published the same total assets at two different precisions, and the checked value fell within each declared rounding interval. This tests the sample rather than certifying every population candidate.

The coverage ceiling, assuming all 3,534 candidates qualify, is 12,237 book-to-market rows (22.46%) and 9,679 complete three-feature rows (17.77%). The three-feature annual ceiling is 9.41% to 22.06%, conservative size-tercile ceilings are 15.54% to 18.97%, and the delisting subgroup ceiling is 213 of 890 (23.93%). The ceiling uses the original security-month keys and caps and adds only candidate keys missing book-to-market. The original thresholds are out of reach for this route.

Claude signed off on closing this route without a replacement panel after reviewing the aggregate evidence and decision logic. Claude did not access the local files. The first complete reconciliation flagged ten cases. The replay corroborated the nine missing-parent-equity exclusions and resolved one reported-precision discrepancy by checking each fact's declared rounding against the expected amount. This is a data-method study, with no change to the 49-trial strategy ledger. The single amendment case cannot establish how WRDS handles revisions generally, and the audited sample cannot certify every candidate.

| Evidence | SHA-256 |
|---|---|
| Frozen fresh audit sample | `edccb4ea6a0ae7864a91a97cc75764fdf0ef87cabd4086f72d336fb6e7c24e0d` |
| Final audit reconciliation | `48ddeb0f9823b363bec9a4b2fbb45d677381eaccc44c143cc6b4b497fdf4cb3f` |
| Coverage ceiling and denominator counts | `86989dd3670bec8a710f19054343637a0bb7d8d2659ee64f2af7d9ab4e7c22b3` |

No replacement panel was built. No returns or confirmation-period data were used.
