"""Replay the SEC-anchored quarterly revenue pilot using both vendor extracts."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import exchange_calendars as xc
import pandas as pd

ROOT = Path(__file__).resolve().parents[1] / "indicators_data/wrds/dual_fundamentals"
DEVELOPMENT_END = pd.Timestamp("2024-12-31")


@dataclass(frozen=True)
class Filing:
    accession: str
    accepted_utc: str
    dollars: int | None

    @property
    def local_date(self) -> pd.Timestamp:
        return pd.Timestamp(pd.Timestamp(self.accepted_utc).tz_convert("America/New_York").date())


@dataclass(frozen=True)
class Quarter:
    ric: str
    isin: str
    gvkey: str
    period: str
    wrds_period: str
    filings: tuple[Filing, ...]
    last_tradable: str | None = None


# Apple reports a Saturday fiscal close. Compustat labels that quarter with month-end.
PILOT = (
    Quarter("AAPL.O", "US0378331005", "001690", "2023-12-30", "2023-12-31", (
        Filing("0000320193-24-000006", "2024-02-01T23:03:38Z", 119_575_000_000),
    )),
    Quarter("RGEN.O", "US7599161095", "012181", "2024-06-30", "2024-06-30", (
        Filing("0000950170-24-087981", "2024-07-30T21:04:52Z", 154_073_000),
        Filing("0001193125-24-221406", "2024-09-18T20:21:31Z", None),
        Filing("0000950170-24-127845", "2024-11-18T17:08:36Z", 158_839_000),
    )),
    Quarter("TWTR.N^J22", "US90184L1026", "018872", "2022-06-30", "2022-06-30", (
        Filing("0001418091-22-000143", "2022-07-22T12:00:46Z", 1_176_660_000),
    ), last_tradable="2022-10-27"),
)


def select_revenue(filings, session, wrds, lseg, *, prefer="wrds", allow_sec_reconstruction=False):
    """Use the latest public filing vintage, then the first eligible vendor."""
    if prefer not in ("wrds", "lseg"):
        raise ValueError("Unknown source preference")
    available = [f for f in filings if f.local_date < session]
    if not available:
        return None, "awaiting_filing", None, None
    filing = max(available, key=lambda f: pd.Timestamp(f.accepted_utc))
    if filing.dollars is None:
        return None, "filing_withdrawn", filing.accession, None

    # Snapshot dates are date-only. A vintage from session t can be used on t+1.
    cutoff = session - pd.Timedelta(days=1)
    active = [(start, end, value) for start, end, value in wrds if start <= cutoff and cutoff <= end]
    if len(active) > 1:
        return None, "overlapping_wrds_versions", filing.accession, None
    candidates = {}
    if active and active[0][2] == filing.dollars:
        candidates["wrds"] = (active[0][2], str(active[0][0].date()), "wrds_snapshot")
    # A historical LSEG query cannot establish first-seen vendor availability.
    # SEC proof dates the exact value, so label this as a filing reconstruction.
    if allow_sec_reconstruction and filing.dollars in lseg:
        candidates["lseg"] = (filing.dollars, None, "lseg_sec_anchored")
    other = "lseg" if prefer == "wrds" else "wrds"
    chosen = candidates.get(prefer) or candidates.get(other)
    if chosen is None:
        return None, "no_verified_vendor_value", filing.accession, None
    value, vintage, provenance = chosen
    return value, provenance, filing.accession, vintage


def snapshot_end(value):
    """Translate an open-ended vendor date without constructing a year-9999 timestamp."""
    return DEVELOPMENT_END if pd.isna(value) or value == "9999-12-31" else pd.Timestamp(value)


def vendor_values(quarter, directory):
    wrds = pd.read_csv(directory / f"{quarter.ric}_wrds.csv", dtype=str)
    wrds = wrds.loc[
        wrds.gvkey.eq(quarter.gvkey) & wrds.datadate.eq(quarter.wrds_period)
        & wrds.curcdq.eq("USD") & wrds.saleq.notna()
    ]
    snapshots = sorted({
        (pd.Timestamp(row.pitdate1), snapshot_end(row.pitdate2),
         Decimal(row.saleq) * 1_000_000)
        for row in wrds.itertuples()
    })
    lseg = pd.read_csv(directory / f"{quarter.ric}_lseg.csv", dtype=str)
    lseg = lseg.loc[
        lseg["ISIN"].eq(quarter.isin) & lseg["Date"].eq(quarter.period)
        & lseg["Currency"].eq("USD") & lseg["Total Revenue"].notna()
    ]
    return snapshots, {Decimal(v) for v in lseg["Total Revenue"]}


def replay(directory=ROOT, *, prefer="wrds", allow_sec_reconstruction=False):
    calendar = xc.get_calendar("XNYS")
    events = []
    for quarter in PILOT:
        wrds, lseg = vendor_values(quarter, directory)
        previous = None
        start = quarter.filings[0].local_date - pd.Timedelta(days=3)
        end = DEVELOPMENT_END
        if quarter.last_tradable:
            end = pd.Timestamp(calendar.next_session(quarter.last_tradable).date())
        for session in calendar.sessions_in_range(start, end):
            session = pd.Timestamp(session.date())
            current = select_revenue(
                quarter.filings, session, wrds, lseg, prefer=prefer,
                allow_sec_reconstruction=allow_sec_reconstruction,
            )
            if quarter.last_tradable and session > pd.Timestamp(quarter.last_tradable):
                current = (None, "no_longer_tradable", None, None)
            if current != previous:
                value, status, accession, vendor_date = current
                events.append({
                    "isin": quarter.isin, "ric": quarter.ric, "gvkey": quarter.gvkey,
                    "fiscal_period_end": quarter.period, "wrds_period_end": quarter.wrds_period,
                    "effective_session": str(session.date()), "revenue_usd": value,
                    "status": status, "sec_accession": accession, "vendor_vintage": vendor_date,
                })
                previous = current
    return pd.DataFrame(events)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefer", choices=["wrds", "lseg"], default="wrds")
    parser.add_argument("--allow-sec-reconstruction", action="store_true",
                        help="research only: permit LSEG values dated by matching SEC filings")
    args = parser.parse_args()
    mode = "sec_reconstructed" if args.allow_sec_reconstruction else "vendor_dated"
    output = ROOT / f"revenue_events_{args.prefer}_first_{mode}.csv"
    events = replay(prefer=args.prefer, allow_sec_reconstruction=args.allow_sec_reconstruction)
    events.to_csv(output, index=False)
    print(events.to_string(index=False))
