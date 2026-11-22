"""Assemble accession evidence from cutoff-filtered SEC facts and WRDS fiscal labels."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from TrainingData.pit.edgar_preferred import preferred_evidence
from TrainingData.pit.fundamentals_gate import CALENDAR, END
from TrainingData.pit.fundamentals_pipeline import digest, load_ccm_links, load_snapshot


def duration_fact(facts, accession, end, minimum, maximum):
    """Accept only one duration/value pair ending at the accession's report period."""
    options = set()
    for fact in facts:
        if fact["accn"] != accession or fact["end"] != end or "start" not in fact:
            continue
        start = pd.Timestamp(fact["start"])
        if minimum <= (pd.Timestamp(end) - start).days <= maximum:
            options.add((start, fact["val"]))
    return next(iter(options)) if len(options) == 1 else (pd.NaT, None)


def instant_fact(facts, accession, end):
    values = {f["val"] for f in facts if f["accn"] == accession and f["end"] == end and "start" not in f}
    return next(iter(values)) if len(values) == 1 else None


def accession_receipts(submissions, facts, spans, labels, source):
    """Keep exact-date matches and record why an accession cannot be mapped."""
    receipts, unresolved = [], []
    for filing in submissions.itertuples(index=False):
        period = pd.Timestamp(filing.reportDate)
        acceptance = pd.Timestamp(filing.acceptanceDateTime)
        if pd.isna(acceptance) or acceptance.tzinfo is None or acceptance > CALENDAR.session_close(END):
            raise ValueError("Invalid development accession acceptance time")
        public_date = pd.Timestamp(acceptance.tz_convert("America/New_York").date())
        if period > END or period > public_date:
            raise ValueError("Invalid development filing period")
        active = spans.loc[spans.start.le(period) & spans.stop.ge(public_date)]
        issuers = active.gvkey.unique()
        key = {"cik": filing.cik, "accession": filing.accessionNumber, "period": period}
        if len(issuers) != 1:
            unresolved.append(dict(key, reason="missing_or_ambiguous_historical_issuer"))
            continue
        gvkey = issuers[0]
        fiscal = labels.get((gvkey, period))
        if fiscal is None:
            unresolved.append(dict(key, reason="missing_or_conflicting_exact_fiscal_labels"))
            continue
        fiscal_year, quarter, year_end = fiscal
        if (filing.form.startswith("10-K") and quarter != 4) or (
            filing.form.startswith("10-Q") and quarter not in (1, 2, 3)
        ):
            unresolved.append(dict(key, reason="form_and_vendor_fiscal_quarter_conflict"))
            continue
        date = filing.reportDate
        accession = filing.accessionNumber
        assets = instant_fact(facts.get("Assets", []), accession, date)
        equity = instant_fact(facts.get("StockholdersEquity", []), accession, date)
        preferred, preferred_basis = preferred_evidence(facts, accession, date)
        base = dict(key, gvkey=gvkey, form=filing.form, accepted_at=acceptance, basis="US-GAAP",
                    currency="USD", consolidated=True, fiscal_year=int(fiscal_year),
                    fiscal_quarter=int(quarter), fiscal_year_end=int(year_end), assets=assets,
                    parent_equity=equity, preferred=preferred, preferred_basis=preferred_basis,
                    preferred_verified=preferred is not None and preferred >= 0,
                    receipt=source)
        durations = [("annual", 350, 380)] if quarter == 4 else [("quarter", 80, 100)]
        if quarter == 3:
            durations.append(("nine_months", 255, 285))
        for kind, lower, upper in durations:
            start, income = duration_fact(facts.get("NetIncomeLoss", []), accession, date, lower, upper)
            receipts.append(dict(base, income_type=kind, income_start=start, income=income))
    return receipts, unresolved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("snapshot_manifest", type=Path, help="JSON list of verified snapshot basenames")
    args = parser.parse_args()
    base = args.input
    paths = json.loads(args.snapshot_manifest.read_text())
    labels = []
    vendor_sources = {}
    for name in paths:
        if Path(name).name != name:
            raise ValueError("Expected local WRDS basename")
        path = base / name
        vendor_sources[name] = digest(path)
        quarantine = []
        rows = load_snapshot([path], quarantined=quarantine)
        labels.append(rows[["gvkey", "period", "fyearq", "fqtr", "fiscal_year_end"]].drop_duplicates())
    labels = pd.concat(labels, ignore_index=True).dropna().drop_duplicates()
    labels = labels.loc[~labels.duplicated(["gvkey", "period"], keep=False)]
    lookup = {r[:2]: r[2:] for r in labels.itertuples(index=False, name=None)}
    roster = pd.read_csv(base / "roster.csv", parse_dates=["signal"])
    links = load_ccm_links(sorted(base.glob("ccm_*.csv.gz")), roster)
    spans = links[["gvkey", "cik", "start", "stop"]].drop_duplicates()
    receipts, unresolved = [], []
    for cik, group in spans.groupby("cik"):
        submissions_path = base / "edgar_metadata" / f"{cik}.csv"
        facts_path = base / "edgar_facts" / f"{cik}.json"
        if not submissions_path.exists() or not facts_path.exists():
            unresolved.append({"cik": cik, "reason": "missing_sec_filing_source"})
            continue
        filings = pd.read_csv(submissions_path, dtype=str).drop_duplicates()
        facts = json.loads(facts_path.read_text())
        source = f"sec-submissions:{digest(submissions_path)};sec-companyfacts:{digest(facts_path)}"
        preferred_path = base / "sec_preferred_evidence" / f"{cik}.json"
        if preferred_path.exists():
            facts.update(json.loads(preferred_path.read_text()))
            source += f";sec-preferred:{digest(preferred_path)}"
        valid, rejected = accession_receipts(filings, facts, group, lookup, source)
        receipts.extend(valid)
        unresolved.extend(rejected)
    if not receipts:
        raise RuntimeError("No exact-date receipts available")
    out = base / "candidate_filing_contexts.parquet"
    pd.DataFrame(receipts).to_parquet(out, index=False)
    pd.DataFrame(unresolved).to_parquet(base / "unresolved_filing_contexts.parquet", index=False)
    manifest = {"candidate_sha256": digest(out), "vendor_sources": vendor_sources,
                "snapshot_selection_sha256": digest(args.snapshot_manifest)}
    (base / "candidate_filing_context_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"{len(receipts)} candidate receipts and {len(unresolved)} unresolved source records")


if __name__ == "__main__":
    main()
