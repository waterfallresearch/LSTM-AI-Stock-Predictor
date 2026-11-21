# WRDS data inventory for the stock predictor

Audited 2026-11-21 using the connected WRDS account. Inventory covers 247 libraries returned by WRDS and 5,813 PostgreSQL relations with schema USAGE and table SELECT metadata privileges. The full inventory is TrainingData/indicators_data/wrds/entitled_catalog.csv. This is a metadata audit, with targeted data queries as noted below. It does not establish population, period coverage, or redistribution rights for every relation.

| Priority | WRDS source | Use and validation status |
|---|---|---|
| First fundamentals addition | comp_snapshot.wrds_csq_pit, wrds_csq_unrestated, wrds_csq_restated and annual counterparts | Live Repligen query confirmed separate original and amended revenue. Join on snapshot effective dates, preserve original and restated versions, and verify accounting definitions against SEC. |
| First identity and universe addition | crsp_a_indexes.dsp500list_v2, crsp_a_ccm.ccmxpf_lnkhist, crsp_a_stock.stksecurityinfohist | Independent S&P 500 membership and effective-dated PERMNO-to-GVKEY links. Index membership start dates span 1925–2025 in the queried table. Verify listing-class links against dated security identifiers. |
| First cross-sectional addition | comp.co_hgic, crsp_a_stock.stkshares and dsf_v2 | Historical GICS intervals, date-effective shares, market-cap/size, sector-relative signals. Metadata confirmed the relevant fields. Check coverage and publication lag before treating effective dates as availability dates. |
| Price and execution cross-check | crsp_a_stock.dsf_v2, stkdelists, stkdistributions | Daily OHLCV, returns, bid/ask fields, adjustment factors, distribution and delisting outcomes. Verify quote definitions and missingness. Daily bid/ask fields do not establish next-open quotes or depth. |
| Market context and attribution | frb.rates_daily, frb.fx_daily, tr_ds_econ.ecodata, ff.fivefactors_daily | Treasury yields, Aaa/Baa yields, broad dollar measures, economic series and factor attribution. Check availability and release vintages. |
| Earnings and analyst estimates | comp_na_daily_all.fundq rdq, ibessamp_kpi, zacksamp.eps_cons_daily | Compustat provides a date field, with announcement timing still to validate. I/B/E/S US KPI summary has one distinct fiscal-period date (2020-12-01). The Zacks sample observations end 2012-10-26. No full research-window EPS consensus was identified. |
| Later event pilot | ciqsamp_keydev.wrds_keydev_trial, ravenpack_trial.rpa_full_equities | Catalog metadata shows UTC announcement/entry or story time and event or sentiment fields. Trial coverage and identifier mapping need verification before any experiment. |
| Lower priority for the daily strategy | cboe options-related tables, optionmsamp_us, TAQ samples, TRACE, short-volume samples | Candidates for volatility, intraday execution, credit, or short-flow research. Entitlement depth, usable sample period and incremental value remain unverified. |

## Repligen 2024 Q2 live check

Company GVKEY 012181, period end 2024-06-30. In millions of USD.

| Snapshot start | Saleq | Oiadpq |
|---|---:|---:|
| 2024-07-30 | 154.073 | 7.106 |
| 2024-11-12 | 160.675 | 13.422 |
| 2024-11-28 | 158.839 | 12.731 |

The original and amended revenue figures match the SEC filing. The separate unrestated and restated tables also returned 154.073 and 158.839. The report date rdq remained 2024-07-30 even on amended versions. Use snapshot availability dates and a conservative session cutoff. The intermediate release needs source reconciliation. Oiadpq did not match SEC operating income, so leave it out until its accounting basis is reconciled.

- https://wrds-www.wharton.upenn.edu/documents/2180/WRDS_SP_Webinar_Feb_002.pdf
- https://www.sec.gov/Archives/edgar/data/730272/000095017024127845/rgen-20240630.htm

The next dataset build has a clear starting point in versioned Compustat statements, CRSP security and membership checks, historical GICS, and dated shares. Keep this inventory and any new predictor data separate from the frozen head-to-head.
