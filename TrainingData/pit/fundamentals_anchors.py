"""Reconcile original EDGAR assets to independently dated WRDS observations."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from TrainingData.pit.edgar_coverage import KEY, dated_links, sec_get
from TrainingData.pit.fundamentals_gate import OUT, filing_session

FACT_TAGS = (
    "Assets", "StockholdersEquity", "NetIncomeLoss", "ProfitLoss",
    "PreferredStockValue", "PreferredStockCarryingValue",
)


def filter_companyfacts(cik: str, payload: dict) -> dict:
    if str(payload["cik"]).zfill(10) != cik:
        raise ValueError("Company Facts CIK mismatch")
    gaap = payload["facts"].get("us-gaap", {})
    return {
        tag: [
            {key: fact[key] for key in ("accn", "end", "start", "val", "filed", "form") if key in fact}
            for fact in gaap.get(tag, {}).get("units", {}).get("USD", [])
            if "2014-01-01" <= fact.get("end", "") <= "2024-12-31"
            and "2014-01-01" <= fact.get("filed", "") < "2024-12-31"
            and fact.get("form") in ("10-Q", "10-Q/A", "10-K", "10-K/A")
        ]
        for tag in FACT_TAGS
    }


def download_facts() -> None:
    import requests

    directory = OUT / "edgar_facts"
    directory.mkdir(exist_ok=True)
    ids = sorted(path.stem for path in (OUT / "edgar_metadata").glob("*.csv"))
    headers = {"User-Agent": os.environ.get("SEC_USER_AGENT", "Historical fundamentals research")}

    def fetch(cik):
        path = directory / f"{cik}.json"
        if not path.exists():
            try:
                payload = sec_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", headers)
                filtered = filter_companyfacts(cik, payload)
                temporary = path.with_suffix(".tmp")
                temporary.write_text(json.dumps(filtered, separators=(",", ":")))
                temporary.replace(path)
            except requests.HTTPError as exc:
                return {"http_status": exc.response.status_code}
            except (requests.RequestException, ValueError, KeyError) as exc:
                return {"error": type(exc).__name__}
        return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    with ThreadPoolExecutor(max_workers=8) as pool:
        manifest = dict(zip(ids, pool.map(fetch, ids), strict=True))
    (OUT / "edgar_fact_manifest.json").write_text(json.dumps(manifest, sort_keys=True))
    print(f"Cached {sum('sha256' in record for record in manifest.values())}/{len(ids)} CIKs")
    print(json.dumps({cik: record for cik, record in manifest.items() if "sha256" not in record}))


def reconcile_assets(filings: pd.DataFrame, facts: pd.DataFrame, snapshots: pd.DataFrame) -> pd.DataFrame:
    """Match original asset facts on accession, report end, and exact dollars."""
    submissions = filings.loc[filings.form.isin(["10-K", "10-Q"])].rename(
        columns={"accessionNumber": "accession", "reportDate": "period",
                 "acceptanceDateTime": "accepted_at"}
    )
    key = ["cik", "accession", "period"]
    # A comparative instant in a later filing cannot match its report-end metadata.
    assets = facts.loc[facts.start.isna(), key + ["dollars"]].drop_duplicates()
    assets = assets.loc[~assets.duplicated(key, keep=False)]
    matched = submissions.merge(assets, on=key, validate="one_to_one")
    matched["dollars"] = pd.to_numeric(matched.dollars)
    vendor = snapshots.assign(dollars=(snapshots.atq * 1_000_000).round(4))
    matched = matched.merge(vendor, on=["cik", "period", "dollars"])
    matched = matched.loc[matched.dollars.gt(0)].copy()
    matched["usable"] = [
        filing_session(accepted, vintage)
        for accepted, vintage in zip(matched.accepted_at, matched.vintage, strict=True)
    ]
    matched = matched.dropna(subset=["usable"])
    return matched.sort_values("usable").drop_duplicates(["gvkey"] + key, keep="first")


def admit_links(roster: pd.DataFrame, windows: pd.DataFrame, anchors: pd.DataFrame) -> pd.DataFrame:
    """Resolve only unique, in-window issuer pairs with two already-public anchors."""
    pair = ["gvkey", "cik"]
    candidates = windows[KEY + pair].drop_duplicates()
    security_conflict = candidates.duplicated(KEY, keep=False)
    issuer_map = candidates[["signal"] + pair].drop_duplicates()
    issuer_conflict = issuer_map.duplicated(["signal", "gvkey"], keep=False) | (
        issuer_map.duplicated(["signal", "cik"], keep=False)
    )
    valid_map = issuer_map.loc[~issuer_conflict]
    candidates = candidates.loc[~security_conflict].merge(valid_map, on=["signal"] + pair)
    trials = windows.merge(candidates).merge(roster[KEY + ["prior_session"]], on=KEY)
    trials = trials.merge(anchors[pair + ["period", "usable"]], on=pair)
    fiscal = pd.to_datetime(trials.period)
    valid = (
        fiscal.between(pd.to_datetime(trials.start), pd.to_datetime(trials.stop))
        & trials.usable.le(trials.prior_session)
    )
    # Both anchors must validate the same historical link interval.
    totals = trials.loc[valid].groupby(KEY + pair + ["start", "stop"]).period.nunique()
    passed = totals.loc[totals.ge(2)].reset_index()[KEY + pair + ["start", "stop"]]
    # Overlapping qualifying link windows are quarantined.
    passed = passed.loc[~passed.duplicated(KEY, keep=False)]
    joined = roster.merge(passed, on=KEY, how="left", validate="one_to_one")
    joined["admitted_from"] = joined.prior_session.where(joined.gvkey.notna())
    return joined


def main():
    import wrds

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-facts", action="store_true")
    if parser.parse_args().download_facts:
        download_facts()
        return
    roster_file = OUT / "roster.csv"
    if hashlib.sha256(roster_file.read_bytes()).hexdigest() != (
        "00322c50661b320f9db84b21b9e6d14fc75f174126030c6de727aa6c902adf56"
    ):
        raise RuntimeError("Frozen roster hash mismatch")
    roster = pd.read_csv(roster_file, parse_dates=["signal", "prior_session"])
    with wrds.Connection(wrds_username=os.environ["WRDS_USERNAME"]) as db:
        windows = dated_links(db, roster, include_window=True)
        pairs = windows[["gvkey", "cik"]].drop_duplicates()
        wrds_assets = db.raw_sql("""
            select distinct gvkey, datadate::text as period, pitdate1::text as vintage, atq
            from comp_snapshot.wrds_csq_pit
            where gvkey=any(%(ids)s) and datadate between '2014-01-01' and '2024-12-31'
            and pitdate1 < '2024-12-31' and datafmt='STD' and consol='C'
            and indfmt='INDL' and curcdq='USD' and atq is not null
        """, params={"ids": pairs.gvkey.unique().tolist()})
    filing_frames = []
    facts = []
    for cik in sorted(pairs.cik.unique()):
        path = OUT / "edgar_facts" / f"{cik}.json"
        if not path.exists():
            continue
        filing_frames.append(pd.read_csv(OUT / "edgar_metadata" / f"{cik}.csv", dtype={"cik": str}))
        facts.extend({
            "cik": cik, "accession": row["accn"], "period": row["end"], "start": row.get("start"),
            "dollars": row["val"],
        } for row in json.loads(path.read_text())["Assets"])
    if not filing_frames:
        raise RuntimeError("No cutoff-filtered EDGAR Company Facts available")
    filings = pd.concat(filing_frames).drop_duplicates()
    assets = reconcile_assets(filings, pd.DataFrame(facts), wrds_assets.merge(pairs, on="gvkey"))
    # Publish source evidence only. Applying it to the feature denominator is a separate checkpoint.
    path = OUT / "edgar_wrds_asset_anchors.parquet"
    assets.to_parquet(path, index=False)
    print(json.dumps({
        "candidate_pairs": len(pairs),
        "candidate_ciks_cached": len(filing_frames),
        "matched_accessions": len(assets),
        "pairs_with_two_periods_unrestricted": int(
            assets.groupby(["gvkey", "cik"]).period.nunique().ge(2).sum()
        ),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }, indent=2))


if __name__ == "__main__":
    main()
