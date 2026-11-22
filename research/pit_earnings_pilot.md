# Point-in-time earnings source pilot

The frozen earnings data gate remains unmeasured. This source pilot covers Apple, Microsoft, and two delisted securities, Celgene and Time Warner. It uses no strategy returns, labels or data from the confirmation period.

| Instrument | Non-null quarterly actuals | Same-period estimates in both provisional windows |
|---|---:|---:|
| Apple | 36 | 35 |
| Microsoft | 36 | 35 |
| Celgene | 16 | 15 |
| Time Warner | 10 | 10 |

Workspace returned 6,125 non-null daily estimates and 98 non-null actuals. The provisional dates assume Eastern report time and treat daily calculation dates as end of day, excluding calculation dates on the cutoff session. The same exact vendor period end was required on both legs. These counts measure the availability of candidate inputs in the pilot. Dated identity, split basis, release timestamps, vendor activation and sample clearance remain required before any panel row is admitted.

Two issuer releases illustrate the basis problem. Apple's fiscal quarter ended September 28, 2024, while Workspace labels its vendor period September 30. The Workspace actual of 1.64 matches the issuer's adjusted diluted EPS. The issuer's GAAP diluted EPS was 0.97. Microsoft's quarter ended September 30 and Workspace's actual of 3.30 matches its issuer release. A comparable estimate basis still needs to be demonstrated per event. [Apple release](https://www.apple.com/newsroom/2024/10/apple-reports-fourth-quarter-results/) · [Microsoft release](https://www.microsoft.com/en-us/investor/earnings/fy-2025-q1/press-release-webcast)

The SEC earnings exhibits establish conservative public-availability bounds. Apple’s 8-K was accepted October 31, 2024 at 16:30:25 Eastern, compared with the vendor report clock at 16:31. Microsoft’s 8-K was accepted October 30, 2024 at 16:04:07 Eastern, compared with 16:01 in the vendor report field. Both sources put each event on the same Eastern calendar date if the vendor clock is Eastern, and both SEC events occurred after the regular close. An SEC acceptance timestamp can show that the information was public by that time. It does not establish the vendor’s first activation. [Apple SEC filing index](https://www.sec.gov/Archives/edgar/data/320193/000032019324000120/0000320193-24-000120-index.htm) · [Microsoft SEC filing index](https://www.sec.gov/Archives/edgar/data/789019/000095017024118955/0000950170-24-118955-index.html)

All 98 actuals had identical values in the Workspace Date and Report Date columns. This provides one timestamp series, with historic vendor activation still unverified. LSEG documents I/B/E/S Point-in-Time as a separate delivery and describes effective and activation dates in Quantitative Analytics. Entitlement and a usable export path remain to be tested. [LSEG quant data catalogue](https://www.lseg.com/content/dam/data-analytics/en_us/documents/brochures/lseg-data-for-quant-research-brochure.pdf) · [Quantitative Analytics revisions example](https://developers.lseg.com/en/article-catalog/article/foreshadowing-analyst-revisions-using-linkup-job-postings-data-in-refinitiv-quantitative-analytics)

A follow-up Workspace request returned populated actual EPS, absolute financial period, and currency on all four 2024 Apple observations. The requested extensions for activation and original value produced no columns. A separate request for estimate detail and activation extensions returned an SDK error. These results describe the tested requests. The separately delivered Quantitative Analytics data has yet to be accessed.

The current WRDS browser session redirected to sign-in. Its public documentation identifies unadjusted detail actuals, estimates and split factors, but the existing local inventory found only sample estimate datasets with insufficient period coverage. No WRDS fallback was admitted. [WRDS unadjusted detail guide](https://wrds-www.wharton.upenn.edu/documents/5/A_Note_on_IBES_Unadjusted_Data_pdf.pdf)

The local pilot files are hashed in the acquisition manifest. The consensus CSV hash is `bd003cba9adb0d1ea81d69e1ced7fccfba0ce3a4a00480729beac9e1f3a0d3cc` and the actuals CSV hash is `3fe52ccaf39a74f79588f8177742f11362a5888c3e266b8b8075c539e2f1954d`. Raw vendor data stays local.
