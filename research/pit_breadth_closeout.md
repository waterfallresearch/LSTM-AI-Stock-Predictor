# Portfolio breadth development result

One locked run at clean commit 20ca0e5. 107 month-end signals over 2016–2024. 47 registered trials, with the confirmation period sealed.

| Strategy | Net CAGR | Gross CAGR | Net Sharpe | Max drawdown | Annual turnover | Stress Sharpe | Top-three removal Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|
| Five stocks | 11.56% | 13.14% | 0.503 | -41.05% | 14.19 | 0.461 | 0.416 |
| 100 stocks | 12.61% | 13.02% | 0.705 | -40.83% | 9.14 | 0.687 | 0.696 |
| SPY total return | 14.61% | | 0.854 | -33.70% | | | |
| Eligible equal weight, zero cost | 12.57% | | 0.727 | -39.60% | | | |

**Decision: breadth does not advance.** The paired +0.203 annualized Sharpe point difference met the 0.20 target. Its one-sided 95% lower bound was -0.148 and the two-sided interval was [-0.213, 0.686]. Deflated Sharpe was 0.260 against 0.95. Both stress and top-three removal checks favored breadth. The momentum rank IC averaged -0.0016 over 106 executable monthly comparisons. Average gross exposure was 98.77% versus 98.82%. No discretionary fill was blocked or clipped by the ADV cap at the tested capital.

The result is consistent with reduced concentration and turnover in this sample. It does not establish a reliable broad-basket Sharpe improvement or an incremental ranking edge. Claude reviewed the results and agreed with the locked decision. Cash events, cost totals, net equity, trade counts, fill ordering, Sharpes and drawdowns independently reconciled for both arms. The results JSON contains the annual returns and remaining diagnostics.

Local ignored output directory: wf_pit/breadth. SHA-256 identifiers:

- results.json b53b3b90ee05be4ec14374e1f6996dd3a7647d5fdba064fd7904cb496d8562fd
- prescore_manifest.json e950b2705a63a9ba038f0671624a388c9806a381a26e8396bdfb7173f4fca608
- five_equity.csv c3e791f23375e6a3ba9a35fcd2c12b8201501aa4210f9bcafb2d42ecbff3405f
- broad_equity.csv fee4fe2bfca9a031cdbe1a9da32d2256ad89a0c0f5def4513fce2d7aa783237e
- five_trades.csv 7d342bb70ba291cc4a954b4a46fabe739e6b1db572b979e26ce16a5505a33b29
- broad_trades.csv 176a21a5fecb08a0275bf6d774049e789542c88d08ec3e67f72706e02a131eeb

A future research arm may test a different signal under its own frozen protocol. The breadth result does not authorize confirmation, long-short execution, or deployment.
