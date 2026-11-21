"""Freeze the fundamentals audit roster and probe dated filing evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import exchange_calendars as xc
import pandas as pd

START = pd.Timestamp("2016-01-01")
END = pd.Timestamp("2024-12-31")
ET = "America/New_York"
CALENDAR = xc.get_calendar("XNYS")
OUT = Path(__file__).resolve().parents[1] / "indicators_data/wrds/fundamentals_gate"


def filing_session(acceptance: str, vendor_availability: str) -> pd.Timestamp | None:
    """Return the first usable session, rejecting future or undated evidence."""
    if not isinstance(acceptance, str) or not isinstance(vendor_availability, str):
        raise ValueError("Availability inputs must be timestamp strings")
    public = pd.Timestamp(acceptance)
    if pd.isna(public) or public.tzinfo is None:
        raise ValueError("SEC acceptance requires a timestamp with timezone")
    public = public.tz_convert(ET)
    vendor = pd.Timestamp(vendor_availability)
    if pd.isna(vendor):
        raise ValueError("Vendor availability is missing")
    if vendor.tzinfo is None:
        if len(vendor_availability) != 10:
            raise ValueError("Vendor intraday availability requires a timezone")
        vendor = (vendor + pd.DateOffset(days=1)).tz_localize(ET) - pd.Timedelta(nanoseconds=1)
    cutoff = CALENDAR.session_close(END)
    if max(public, vendor) > cutoff:
        return None
    local_day = public.normalize()
    if public.tz_localize(None) - local_day.tz_localize(None) > pd.Timedelta(hours=17, minutes=30):
        public = local_day + pd.DateOffset(days=1)
    boundary = max(public, vendor)
    day = pd.Timestamp(boundary.tz_convert(ET).date())
    for session in CALENDAR.sessions_in_range(day, END):
        if CALENDAR.session_open(session) > boundary:
            return session
    return None


def freeze_roster(membership: pd.DataFrame) -> pd.DataFrame:
    sessions = CALENDAR.sessions_in_range(START, END)
    month_ends = pd.Series(sessions).groupby(sessions.to_period("M")).last()
    membership = membership.assign(
        mbrstartdt=pd.to_datetime(membership.mbrstartdt),
        mbrenddt=pd.to_datetime(membership.mbrenddt),
    )
    frames = []
    for signal in month_ends:
        active = membership.mbrstartdt.le(signal) & (
            membership.mbrenddt.isna() | membership.mbrenddt.ge(signal)
        )
        ids = membership.loc[active, "permno"]
        if ids.empty or ids.isna().any() or ids.duplicated().any():
            raise ValueError(f"Missing or ambiguous membership on {signal.date()}")
        frames.append(pd.DataFrame({
            "signal": signal,
            "prior_session": CALENDAR.previous_session(signal),
            "permno": ids.astype("int64"),
        }))
    return pd.concat(frames, ignore_index=True).sort_values(["signal", "permno"])


def sec_submissions(columns: dict, cik: str) -> pd.DataFrame:
    """Keep cutoff-safe periodic filing metadata from an EDGAR submissions table."""
    names = ("accessionNumber", "form", "reportDate", "acceptanceDateTime")
    rows = pd.DataFrame({name: columns[name] for name in names})
    acceptance = pd.to_datetime(rows.acceptanceDateTime, utc=True, errors="coerce")
    period = pd.to_datetime(rows.reportDate, errors="coerce")
    keep = (
        acceptance.le(CALENDAR.session_close(END))
        & period.le(END)
        & rows.form.isin(("10-Q", "10-Q/A", "10-K", "10-K/A"))
        & rows.accessionNumber.str.fullmatch(r"\d{10}-\d{2}-\d{6}", na=False)
        & rows.acceptanceDateTime.str.contains(r"(?:Z|[+-]\d{2}:\d{2})$", na=False)
    )
    return rows.loc[keep].assign(cik=cik, acceptanceDateTime=acceptance[keep])


def candidate_links(roster: pd.DataFrame, links: pd.DataFrame) -> pd.DataFrame:
    """Count unique dated candidates while preserving the roster denominator."""
    matches = roster.merge(links, on="permno", how="left")
    active = (
        pd.to_datetime(matches.linkdt).le(matches.signal)
        & pd.to_datetime(matches.linkenddt).ge(matches.signal)
        & matches.gvkey.notna()
        & matches.cik.str.fullmatch(r"0*\d*[1-9]\d*", na=False)
    )
    keys = ["signal", "permno"]
    candidates = matches.loc[active, keys + ["gvkey", "cik"]].drop_duplicates()
    counts = candidates.groupby(keys).size().rename("cik_candidates")
    return roster.join(counts, on=keys).fillna({"cik_candidates": 0}).astype({"cik_candidates": int})


def probe_sources(db) -> dict:
    """Exercise permissions using bounded, pre-confirmation reference queries."""
    from sqlalchemy.exc import DBAPIError

    queries = {
        "dated_cik_gvkey": """
            select cik, gvkey, link_start_date, link_end_date from wrdssec.wciklink_gvkey
            where gvkey = '018872' and link_start_date <= '2022-06-30'
            and link_end_date >= '2022-06-30'
        """,
        "filing_acceptance": """
            select accession, cik, secadate, secatime, rdate, form from wrdssec.wrds_forms
            where accession = '0001418091-22-000147' and secadate < '2024-12-31'
        """,
        "dated_ccm": """
            select gvkey, lpermno from crsp_a_ccm.ccmxpf_lnkhist
            where lpermno = 14295 and linkdt <= '2022-06-30'
            and (linkenddt is null or linkenddt >= '2022-06-30')
        """,
        "ccm_lookup_cik_candidate": """
            select cik, gvkey from crsp_a_ccm.ccm_lookup
            where lpermno = 14295 and linkdt <= '2022-06-30'
            and (linkenddt is null or linkenddt >= '2022-06-30') and cik is not null
        """,
        "snapshot_vintage": """
            select gvkey, atq, ceqq, niq from comp_snapshot.wrds_csq_pit
            where gvkey = '018872' and datadate = '2022-06-30'
            and pitdate1 < '2024-12-31'
        """,
        "crsp_daily_cap_inputs": """
            select permno, permco, dlyprc, shrout from crsp_a_stock.dsf_v2
            where permno = 14295 and dlycaldt = '2022-06-29'
        """,
    }
    results = {}
    for name, sql in queries.items():
        try:
            results[name] = {"rows": len(db.raw_sql(sql))}
        except DBAPIError as exc:
            db.connection.rollback()
            results[name] = {"sqlstate": getattr(exc.orig, "pgcode", None)}
    return results


def main() -> None:
    import wrds

    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    with wrds.Connection(wrds_username=os.environ["WRDS_USERNAME"]) as db:
        membership = db.raw_sql("""
            select permno, mbrstartdt, least(mbrenddt, date '2024-12-31') as mbrenddt
            from crsp_a_indexes.dsp500list_v2
            where mbrstartdt <= '2024-12-31' and (mbrenddt is null or mbrenddt >= '2016-01-01')
        """)
        roster = freeze_roster(membership)
        if not roster.groupby("signal").size().between(495, 510).all():
            raise RuntimeError("Unexpected monthly CRSP roster count")
        contents = roster.to_csv(index=False, lineterminator="\n").encode()
        OUT.mkdir(parents=True, exist_ok=True)
        roster_path = OUT / "roster.csv"
        if roster_path.exists() and roster_path.read_bytes() != contents:
            raise RuntimeError("Frozen roster differs from the current source")
        if not roster_path.exists():
            with roster_path.open("xb") as stream:
                stream.write(contents)
        links = db.raw_sql("""
            select distinct lpermno as permno, gvkey, cik, linkdt,
                least(linkenddt, date '2024-12-31') as linkenddt
            from crsp_a_ccm.ccm_lookup
            where lpermno = any(%(ids)s) and linkdt <= '2024-12-31'
            and (linkenddt is null or linkenddt >= '2016-01-01')
        """, params={"ids": roster.permno.unique().tolist()})
        counts = candidate_links(roster, links).cik_candidates
        results = {
            "security_months": len(roster),
            "signal_months": roster.signal.nunique(),
            "roster_sha256": hashlib.sha256(contents).hexdigest(),
            "cik_candidate_counts": {
                "missing": int(counts.eq(0).sum()),
                "unique": int(counts.eq(1).sum()),
                "ambiguous": int(counts.gt(1).sum()),
            },
            "source_probes": probe_sources(db),
        }
    report = json.dumps(results, indent=2)
    (OUT / "source_probe.json").write_text(report + "\n", encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
