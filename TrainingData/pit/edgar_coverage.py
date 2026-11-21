"""Measure EDGAR filing metadata coverage on the frozen development roster."""
import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

import pandas as pd
import requests

from TrainingData.pit.fundamentals_gate import CALENDAR, END, OUT, sec_submissions

BASE = "https://data.sec.gov/submissions/"
KEY = ["signal", "permno"]
REQUEST_LOCK = Lock()
NEXT_REQUEST = 0.0


def dated_links(db, roster, *, include_window=False):
    links = db.raw_sql("""
        select distinct a.lpermno as permno, a.gvkey, b.cik,
            greatest(a.linkdt, b.linkdt) as start,
            least(a.linkenddt, b.linkenddt, date '2024-12-31') as stop
        from crsp_a_ccm.ccmxpf_lnkhist a
        join crsp_a_ccm.ccm_lookup b on a.lpermno=b.lpermno and a.gvkey=b.gvkey
        where a.lpermno=any(%(ids)s) and a.linktype in ('LC','LU')
        and a.linkprim in ('P','C')
        and greatest(a.linkdt,b.linkdt)<='2024-12-31'
        and least(a.linkenddt,b.linkenddt,date '2024-12-31')>='2016-01-01'
        and b.cik is not null
    """, params={"ids": roster.permno.unique().tolist()})
    links = links.loc[links.cik.str.fullmatch(r"0*\d*[1-9]\d*")].copy()
    links["cik"] = links.cik.str.zfill(10)
    matches = roster.merge(links, on="permno", how="left")
    active = matches.signal.between(pd.to_datetime(matches.start), pd.to_datetime(matches.stop))
    fields = KEY + ["gvkey", "cik"]
    if include_window:
        fields += ["start", "stop"]
    return matches.loc[active, fields].drop_duplicates()


def sec_get(url, headers):
    global NEXT_REQUEST
    with REQUEST_LOCK:
        now = time.monotonic()
        time.sleep(max(0, NEXT_REQUEST - now))
        NEXT_REQUEST = time.monotonic() + 0.20
    response = requests.get(url, headers=headers, timeout=12)
    response.raise_for_status()
    return response.json()


def fetch_filings(cik, output):
    cache = output / f"{cik}.csv"
    if cache.exists():
        return "cached"
    headers = {"User-Agent": os.environ.get("SEC_USER_AGENT", "Historical fundamentals research")}
    try:
        root = sec_get(BASE + f"CIK{cik}.json", headers)
        if str(root["cik"]).zfill(10) != cik:
            raise ValueError("CIK mismatch")
        frames = [sec_submissions(root["filings"]["recent"], cik)]
        for shard in root["filings"]["files"]:
            if shard["filingTo"] < "2014-01-01" or shard["filingFrom"] > "2024-12-31":
                continue
            frames.append(sec_submissions(sec_get(BASE + shard["name"], headers), cik))
        rows = pd.concat(frames).drop_duplicates()
        temporary = cache.with_suffix(".tmp")
        rows.loc[rows.reportDate.ge("2014-01-01")].to_csv(temporary, index=False)
        temporary.replace(cache)
        return "ok"
    except requests.HTTPError as exc:
        return f"http_{exc.response.status_code}"
    except (requests.RequestException, ValueError, KeyError) as exc:
        return type(exc).__name__


def summarize(roster, links, filings, periods):
    counts = links.groupby(KEY).size().rename("link_count")
    roster = roster.join(counts, on=KEY).fillna({"link_count": 0}).astype({"link_count": int})
    unique = links.loc[~links.duplicated(KEY, keep=False)]
    rows = roster.merge(unique, on=KEY, how="left", validate="one_to_one")
    filings = filings.loc[filings.form.isin(["10-K", "10-Q"])].copy()
    filings["acceptanceDateTime"] = pd.to_datetime(filings.acceptanceDateTime, utc=True, format="mixed")
    filings["reportDate"] = pd.to_datetime(filings.reportDate)
    windows = {day: CALENDAR.session_open(day) for day in rows.prior_session.unique()}
    sec_only = rows.loc[rows.link_count.eq(1), KEY + ["prior_session", "cik"]].merge(filings, on="cik")
    recent_sec = (
        sec_only.acceptanceDateTime.lt(sec_only.prior_session.map(windows))
        & sec_only.reportDate.between(sec_only.signal - pd.Timedelta("180 days"), sec_only.prior_session)
    )
    rows["recent_sec_filing"] = pd.MultiIndex.from_frame(rows[KEY]).isin(
        pd.MultiIndex.from_frame(sec_only.loc[recent_sec, KEY]))
    periods = periods.assign(datadate=pd.to_datetime(periods.datadate), vintage=pd.to_datetime(periods.vintage))
    # Exact dates only. Fiscal calendars with vendor-normalized month ends need a separate review.
    issuer_pairs = unique[["gvkey", "cik"]].drop_duplicates()
    by_period = filings.merge(issuer_pairs, on="cik").merge(
        periods, left_on=["gvkey", "reportDate"], right_on=["gvkey", "datadate"]
    )
    matched = rows.dropna(subset=["gvkey"]).merge(by_period, on=["gvkey", "cik"])
    prior = matched.prior_session
    cutoff = prior.map(windows)
    timed = matched.acceptanceDateTime.lt(cutoff) & matched.vintage.lt(prior)
    usable = timed & matched.reportDate.ge(matched.signal - pd.Timedelta("180 days"))
    evidence = matched.loc[usable].sort_values(
        ["reportDate", "acceptanceDateTime", "accessionNumber"]
    ).drop_duplicates(KEY, keep="last")
    rows = rows.merge(evidence[KEY + ["accessionNumber", "form", "reportDate", "acceptanceDateTime"]],
                      on=KEY, how="left", validate="one_to_one")
    rows["filing_period_match"] = rows.accessionNumber.notna()
    rows["exact_period_present"] = pd.MultiIndex.from_frame(rows[KEY]).isin(
        pd.MultiIndex.from_frame(matched[KEY]))
    rows["exact_period_available"] = pd.MultiIndex.from_frame(rows[KEY]).isin(
        pd.MultiIndex.from_frame(matched.loc[timed, KEY]))
    return rows


def main():
    import wrds

    roster_file = OUT / "roster.csv"
    roster_hash = hashlib.sha256(roster_file.read_bytes()).hexdigest()
    if roster_hash != "00322c50661b320f9db84b21b9e6d14fc75f174126030c6de727aa6c902adf56":
        raise RuntimeError("Frozen roster hash mismatch")
    roster = pd.read_csv(roster_file, parse_dates=["signal", "prior_session"])
    with wrds.Connection(wrds_username=os.environ["WRDS_USERNAME"]) as db:
        links = dated_links(db, roster)
        periods = db.raw_sql("""
            select gvkey, datadate, min(pitdate1) as vintage
            from comp_snapshot.wrds_csq_pit where gvkey=any(%(ids)s)
            and datadate between '2014-01-01' and '2024-12-31'
            and pitdate1<'2024-12-31' and datafmt='STD' and consol='C'
            and indfmt='INDL' and curcdq='USD' group by 1,2
        """, params={"ids": links.gvkey.unique().tolist()})
    output = OUT / "edgar_metadata"
    output.mkdir(exist_ok=True)
    ids = sorted(links.cik.unique())
    status = {cik: "cached" for cik in ids if (output / f"{cik}.csv").exists()}
    pending = [cik for cik in ids if cik not in status]
    print(f"Checking {len(ids)} historical CIK candidates", flush=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = {pool.submit(fetch_filings, cik, output): cik for cik in pending}
        for job in as_completed(jobs):
            status[jobs[job]] = job.result()
            if len(status) % 100 == 0:
                print(f"Checked {len(status)}/{len(ids)} CIKs", flush=True)
    (OUT / "edgar_download_status.json").write_text(json.dumps(status))
    frames = [pd.read_csv(output / f"{cik}.csv", dtype={"cik": str})
              for cik in ids if status[cik] in ("ok", "cached")]
    if not frames:
        raise RuntimeError("No EDGAR metadata retrieved")
    filings = pd.concat(frames, ignore_index=True)
    rows = summarize(roster, links, filings, periods)
    rows["download_status"] = rows.cik.map(status).fillna("no_unique_link")
    completed = rows.download_status.isin(["ok", "cached"])
    manifests = {}
    for cik in ids:
        path = output / f"{cik}.csv"
        if status[cik] in ("ok", "cached"):
            manifests[cik] = {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "mtime": path.stat().st_mtime,
                "source": BASE + f"CIK{cik}.json",
            }
    manifest_path = OUT / "edgar_metadata_manifest.json"
    manifest_path.write_text(json.dumps(manifests, sort_keys=True))
    rows.to_parquet(OUT / "edgar_filing_coverage.parquet", index=False)
    result = {
        "roster_sha256": roster_hash,
        "security_months": len(rows),
        "link_counts": {str(key): int(value) for key, value in rows.link_count.value_counts().items()},
        "cik_requests": pd.Series(status).value_counts().to_dict(),
        "filing_metadata_rows": len(filings),
        "metadata_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "coverage_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "unique_link_download_failed": int((rows.link_count.eq(1) & ~completed).sum()),
        "unique_link_download_ok": int(completed.sum()),
        "recent_sec_filing": int(rows.recent_sec_filing.sum()),
        "exact_period_present": int(rows.exact_period_present.sum()),
        "exact_period_available": int(rows.exact_period_available.sum()),
        "filing_period_matches": int(rows.filing_period_match.sum()),
        "by_year": rows.groupby(rows.signal.dt.year).filing_period_match.agg(["sum", "count"]).to_dict("index"),
    }
    report = json.dumps(result, indent=2)
    (OUT / "edgar_filing_coverage_summary.json").write_text(report + "\n")
    print(report, flush=True)


if __name__ == "__main__":
    main()
