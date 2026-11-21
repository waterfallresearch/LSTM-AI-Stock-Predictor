# Dual-source quarterly revenue validation pilot

Live historical extracts from LSEG Workspace and WRDS Compustat Snapshot were compared with SEC disclosures. This is a three-quarter development pilot, with no fitting and no reserved-period outcomes. It tests consolidated USD quarterly revenue only. Preserve reported operating income, adjusted operating measures and EPS as separate concepts.

## Selection and provenance

Match the dated security, company, quarter and USD consolidated revenue. Apple uses an explicit fiscal-quarter mapping between the December 30 issuer end and the December 31 Compustat key. Vendor raw extracts remain in TrainingData/indicators_data/wrds/dual_fundamentals. The WRDS query filtered to industrial format, standardized data and consolidated observations. It retrieved the date-valid versions, not the latest value alone. The LSEG query used TR.TotalRevenue, its period, calculation date and currency, and TR.ISIN.

The default replay requires an active WRDS snapshot that matches the latest SEC filing exactly. Both filing and vendor dates must precede the signal session. Duplicate identical snapshots collapse; overlapping distinct snapshots return missing. A withdrawal invalidates the old figure until a new filing is available. The delisted Twitter example stops after its last executable bar. A future full panel must also apply historical membership and audited crosswalks.

An opt-in research replay can use LSEG values reconstructed from an exact match with the latest available SEC filing. Its rows are explicitly labelled lseg_sec_anchored. The reconstructed observation is dated from the SEC disclosure. That date does not prove the vendor published or delivered the observation then. No value from unverified vendor history is admitted to default training-grade output. Prefer either vendor with --prefer lseg or --prefer wrds. If the preferred source has no eligible value, the other source is tried under the same gates.

## Live evidence

| Security | Fiscal quarter | Finding |
|---|---|---|
| Apple | 2023-12-30 | Both vendors matched filed revenue of $119.575B. The SEC filing supports an opt-in reconstruction on Feb 2, 2024. The dated WRDS version first becomes eligible on Feb 5. |
| Repligen | 2024-06-30 | WRDS supplies the original $154.073M from Jul 31. LSEG returned $158.839M against a July calculation date, so it cannot supply the July figure. The Sep 18 non-reliance disclosure blocks stale data starting Sep 19. The SEC-verified amended $158.839M is eligible from Nov 19 in the opt-in replay, and as a dated WRDS value from Nov 29. The unverified $160.675M intermediate snapshot is excluded. |
| Twitter | 2022-06-30 | Both feeds matched $1.176660B filed with the July 22 results release. The replay first admits it on Jul 25 and stops after the Oct 27 last tradable bar. |

Run from the repository root with python -m TrainingData.pit.dual_fundamentals. Repeat with --allow-sec-reconstruction to audit the reconstruction and add --prefer lseg to test fallback in the opposite direction. The emitted CSV files store accession, vendor snapshot date when verified, source status, period identifiers and effective session.

Claude reviewed the design and pilot, flagging open-ended dates, provenance, overlapping intervals and delisting. The replay caps open-ended snapshots at the development end, fails closed on distinct overlapping versions, requires explicit opt-in for SEC reconstruction and retires Twitter after its final tradable session. The local regression tests cover the backfilled amendment, withdrawal, fallback, missing values and open-ended dates.

This pilot establishes that the feeds can complement one another for a validated revenue concept. It does not verify historical LSEG feed vintages or full-universe coverage. The dated identity crosswalk, broader filing-anchored metric checks and coverage audit are still prerequisites for a full training dataset.
