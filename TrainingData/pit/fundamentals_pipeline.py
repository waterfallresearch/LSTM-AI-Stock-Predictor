"""Assemble local WRDS exports and accession evidence into a development panel."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from lxml import html

from TrainingData.pit.fundamentals_anchors import admit_links
from TrainingData.pit.fundamentals_features import (
    aggregate_market_cap, build_features, coverage, fourth_quarter, reconcile_facts,
)
from TrainingData.pit.fundamentals_gate import CALENDAR, END, filing_session

ROSTER_SHA256 = "00322c50661b320f9db84b21b9e6d14fc75f174126030c6de727aa6c902adf56"
WRDS_COLUMNS = {
    "Global Company Key": "gvkey", "Data Date": "period", "Point Date": "vintage",
    "Fiscal Year-end Month": "fiscal_year_end", "Assets - Total": "atq",
    "CommonOrdinary Equity - Total": "ceqq", "Net Income (Loss)": "niq",
    "Level of Consolidation": "consol", "Industry Format": "indfmt",
    "Data Format": "datafmt", "Currency Code - Interim Issue": "currency",
}
WRDS_CSV_ALIASES = {"datadate": "period", "pointdate": "vintage", "pitdate": "vintage", "pitdate1": "vintage",
                    "fyr": "fiscal_year_end", "curcdq": "currency"}
CRSP_DAILY_COLUMNS = {
    "PERMNO": "permno", "PERMCO": "permco", "Daily Calendar Date": "session",
    "Security Information Start Date": "start", "Security Information End Date": "stop",
    "Security Type": "securitytype", "Security Sub-Type": "securitysubtype",
    "Daily Price": "price", "Daily Price Flag": "price_flag", "Shares Outstanding": "shrout",
}
CRSP_NAMES_COLUMNS = {
    key: value for key, value in CRSP_DAILY_COLUMNS.items()
    if value in {"permno", "permco", "start", "stop", "securitytype", "securitysubtype"}
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_wrds(path, columns, aliases=None):
    if path.name.lower().endswith((".csv", ".csv.gz")):
        frame = pd.read_csv(path, dtype=str).rename(columns=columns)
        if aliases is not None:
            frame.columns = frame.columns.str.lower()
            frame = frame.rename(columns=aliases)
        return frame
    tables = []
    for table in html.parse(str(path)).xpath("//table"):
        rows = [[cell.text_content().strip() for cell in row.xpath("./th|./td")]
                for row in table.xpath(".//tr")]
        for index, cells in enumerate(rows):
            if set(columns).issubset(cells):
                tables.append(pd.DataFrame(rows[index + 1:], columns=cells))
                break
    if len(tables) != 1:
        raise ValueError(f"Expected one WRDS export table in {path.name}")
    return tables[0].rename(columns=columns)


def load_snapshot(paths, *, quarantined=None):
    """Read daily browser snapshots with their query point dates intact."""
    frames = [_read_wrds(path, WRDS_COLUMNS, WRDS_CSV_ALIASES) for path in paths]
    data = pd.concat(frames, ignore_index=True)
    extras = [column for column in ("niy", "pstkq", "fqtr", "fyearq") if column in data]
    data = data[list(WRDS_COLUMNS.values()) + extras].copy()
    data["gvkey"] = data.gvkey.astype(str).str.zfill(6)
    for field in ("period", "vintage"):
        data[field] = pd.to_datetime(data[field], errors="raise")
    if data[["period", "vintage"]].isna().any().any():
        raise ValueError("Snapshot requires real report and point dates")
    if data[["period", "vintage"]].gt(END).any().any():
        raise ValueError("Confirmation date in WRDS export")
    valid = data.consol.eq("C") & data.indfmt.eq("INDL") & data.datafmt.eq("STD") & data.currency.eq("USD")
    data = data.loc[valid].drop_duplicates()
    key = ["gvkey", "period", "vintage"]
    competing = data.duplicated(key, keep=False)
    if competing.any():
        conflicts = data.loc[competing, key].drop_duplicates().assign(reason="competing_wrds_point_date")
        if quarantined is None:
            raise ValueError("Competing WRDS rows for the same issuer, period and point date")
        quarantined.extend(conflicts.to_dict("records"))
        data = data.loc[~competing].copy()
    for field in ("atq", "ceqq", "niq", *extras):
        data[field] = pd.to_numeric(data[field].replace({".": np.nan, "": np.nan}), errors="raise")
    return data


def load_crsp_daily(paths, prior_sessions):
    """Normalize quote evidence. Expected classes must come from a separate names export."""
    aliases = {"dlycaldt": "session", "secinfostartdt": "start", "secinfoenddt": "stop",
               "dlyprc": "price", "dlyprcflg": "price_flag"}
    frames = [_read_wrds(path, CRSP_DAILY_COLUMNS, aliases) for path in paths]
    data = pd.concat(frames, ignore_index=True)[list(CRSP_DAILY_COLUMNS.values())]
    data["session"] = pd.to_datetime(data.session, errors="raise")
    if data.session.isna().any() or data.session.gt(END).any():
        raise ValueError("Invalid development date in CRSP daily export")
    data = data.loc[data.session.isin(prior_sessions)
                    & data.securitytype.eq("EQTY") & data.securitysubtype.eq("COM")].copy()
    data["price"] = pd.to_numeric(data.price.replace({".": np.nan, "": np.nan}), errors="raise")
    data["shrout"] = pd.to_numeric(data.shrout.replace({".": np.nan, "": np.nan}), errors="raise")
    data["price"] = data.price.where(data.price_flag.eq("TR") & data.price.gt(0))
    for field in ("permno", "permco"):
        data[field] = pd.to_numeric(data[field], errors="raise").astype("int64")
    quotes = data[["session", "permno", "permco", "price", "shrout"]].drop_duplicates()
    if quotes.duplicated(["session", "permno", "permco"]).any():
        raise ValueError("Competing CRSP prices or share counts for one class")
    return quotes


def load_crsp_names(paths):
    """Build the expected common-share listing spells independently of quotes."""
    aliases = {"secinfostartdt": "start", "secinfoenddt": "stop"}
    frames = [_read_wrds(path, CRSP_NAMES_COLUMNS, aliases) for path in paths]
    data = pd.concat(frames, ignore_index=True)[list(CRSP_NAMES_COLUMNS.values())]
    start = pd.to_datetime(data.start, errors="raise")
    if start.isna().any() or start.gt(END).any():
        raise ValueError("Names export contains a non-development security start date")
    stop = data.stop.fillna("2024-12-31").replace({"": "2024-12-31", ".": "2024-12-31"})
    if not stop.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
        raise ValueError("Invalid CRSP names interval end date")
    stop = pd.to_datetime(stop.where(stop.le("2024-12-31"), "2024-12-31"), errors="raise")
    common = data.securitytype.eq("EQTY") & data.securitysubtype.eq("COM")
    return data.assign(start=start, stop=stop).loc[
        common & stop.ge(pd.Timestamp("2016-01-01")), ["permno", "permco", "start", "stop"]
    ].astype({"permno": "int64", "permco": "int64"}).drop_duplicates()


def load_crsp_delistings(paths):
    """Parse only verified development-period CRSP security delisting dates."""
    frames = [_read_wrds(path, {"PERMNO": "permno", "Delisting Date": "delist_date"},
                         {"delistingdt": "delist_date"}) for path in paths]
    events = pd.concat(frames, ignore_index=True)[["permno", "delist_date"]].drop_duplicates()
    events["delist_date"] = pd.to_datetime(events.delist_date, errors="raise")
    if events.delist_date.isna().any() or events.delist_date.gt(END).any():
        raise ValueError("Invalid development delisting date")
    events["permno"] = events.permno.astype("int64")
    if events.permno.duplicated().any():
        raise ValueError("Competing CRSP security delisting dates")
    return events


def load_ccm_links(paths, roster):
    """Intersect dated CCM security links with historical CIK descriptions."""
    keys = ["gvkey", "permno", "linkdt", "linkenddt", "linktype", "linkprim",
            "hchgdt", "hchgenddt", "hcik"]
    frames = [pd.read_csv(path, dtype=str, usecols=keys) for path in paths]
    data = pd.concat(frames, ignore_index=True)
    for field in ("linkdt", "linkenddt", "hchgdt", "hchgenddt"):
        data[field] = pd.to_datetime(data[field], errors="raise")
        if data[field].isna().any() or data[field].gt(END).any():
            raise ValueError(f"CCM extract has an invalid development {field}")
    eligible = data.linktype.isin(["LC", "LU"]) & data.linkprim.isin(["P", "C"])
    eligible &= data.hcik.str.fullmatch(r"0*\d*[1-9]\d*", na=False)
    data = data.loc[eligible].copy()
    data["gvkey"] = data.gvkey.str.zfill(6)
    data["permno"] = data.permno.astype("int64")
    data["cik"] = data.hcik.str.zfill(10)
    data["start"] = data[["linkdt", "hchgdt"]].max(axis=1)
    data["stop"] = data[["linkenddt", "hchgenddt"]].min(axis=1)
    identity = ["permno", "gvkey", "cik"]
    spells = data.loc[data.start.le(data.stop), identity + ["start", "stop"]].drop_duplicates()
    spells = spells.sort_values(identity + ["start", "stop"])
    spells["last_end"] = spells.groupby(identity).stop.cummax()
    previous_end = spells.groupby(identity).last_end.shift()
    splits = previous_end.isna() | spells.start.gt(previous_end + pd.Timedelta(days=1))
    spells["span"] = splits.cumsum()
    spans = spells.groupby(identity + ["span"], as_index=False).agg(start=("start", "min"), stop=("stop", "max"))
    joined = roster[["signal", "permno"]].merge(
        spans.drop(columns="span"), on="permno"
    )
    return joined.loc[joined.signal.between(joined.start, joined.stop)].drop_duplicates()


def market_inputs(roster, listing, quotes, delistings):
    """Join prior-session common class evidence. Quotes use CRSP shares in thousands."""
    listing, quotes, delistings = listing.copy(), quotes.copy(), delistings.copy()
    date_columns = ((listing, ("start", "stop")), (quotes, ("session",)),
                    (delistings, ("delist_date",)))
    for table, fields in date_columns:
        for field in fields:
            table[field] = pd.to_datetime(table[field], errors="raise")
            if table[field].gt(END).any():
                raise ValueError(f"Confirmation date in CRSP {field}")
    listing["stop"] = listing.stop.fillna(END)
    if listing.start.isna().any() or listing.stop.lt(listing.start).any():
        raise ValueError("Invalid CRSP security interval")
    sessions = pd.DataFrame({"session": roster.prior_session.unique()})
    classes = sessions.merge(listing, how="cross")
    active = classes.session.between(classes.start, classes.stop)
    classes = classes.loc[active, ["session", "permco", "permno"]].drop_duplicates()
    if classes.duplicated(["session", "permno"]).any():
        raise ValueError("Competing expected issuers for a security")
    quoted = quotes.assign(shares=pd.to_numeric(quotes.shrout) * 1000)
    caps = aggregate_market_cap(quoted[["session", "permco", "permno", "price", "shares"]], classes)
    mapped = classes.merge(caps, on=["session", "permco"], validate="many_to_one")
    panel = roster.merge(mapped, left_on=["prior_session", "permno"],
                         right_on=["session", "permno"], how="left", validate="one_to_one")
    panel = panel.rename(columns={"session": "cap_session"})
    valid = panel.loc[panel.cap.notna()].sort_values(["signal", "cap", "permco"])
    issuers = valid.drop_duplicates(["signal", "permco"]).copy()
    ranks = issuers.groupby("signal").cumcount()
    counts = issuers.groupby("signal").cap.transform("size")
    issuers["size_tercile"] = 1 + 3 * ranks // counts
    panel = panel.merge(issuers[["signal", "permco", "size_tercile"]],
                        on=["signal", "permco"], how="left", validate="many_to_one")
    return panel.merge(delistings[["permno", "delist_date"]], on="permno", how="left",
                       validate="many_to_one")


def validate_contexts(contexts, metadata_dir, facts_dir):
    """Require each review receipt to agree with accession-specific public evidence."""
    sources = []
    for cik, rows in contexts.groupby("cik", dropna=False):
        if not isinstance(cik, str) or len(cik) != 10 or not cik.isascii() or not cik.isdecimal():
            raise ValueError("Invalid filing-context CIK")
        metadata = metadata_dir / f"{cik}.csv"
        facts_file = facts_dir / f"{cik}.json"
        sources.extend([metadata, facts_file])
        submissions = pd.read_csv(metadata, dtype=str)
        facts = json.loads(facts_file.read_text())
        for row in rows.itertuples(index=False):
            if not isinstance(row.accession, str):
                raise ValueError("Missing accession")
            matching = submissions.loc[
                submissions.accessionNumber.eq(row.accession) & submissions.form.eq(row.form)
                & submissions.reportDate.eq(row.period.date().isoformat())
                & pd.to_datetime(submissions.acceptanceDateTime, utc=True, format="mixed").eq(row.accepted_at)
            ]
            if len(matching) != 1 or not isinstance(row.receipt, str) or not row.receipt.strip():
                raise ValueError(f"Missing or conflicting filing evidence for {row.accession}")
            period = row.period.date().isoformat()
            start = row.income_start.date().isoformat() if pd.notna(row.income_start) else None
            for tagged, declared in (
                (reconcile_facts(facts["Assets"], row.accession, period), row.assets),
                (reconcile_facts(facts["StockholdersEquity"], row.accession, period), row.parent_equity),
                (reconcile_facts(facts["NetIncomeLoss"], row.accession, period, start), row.income),
            ):
                if pd.notna(declared) and tagged != declared:
                    raise ValueError(f"Filing receipt disagrees with SEC facts for {row.accession}")
    return sources


def _filing_income(filing, filings, nine_months, lookup):
    if filing.form.startswith("10-Q"):
        return filing.income, filing.income_start, (filing.accession,), filing.accepted_at
    if not 350 <= (filing.period - filing.income_start).days <= 380:
        return np.nan, pd.NaT, (), filing.accepted_at
    candidates = nine_months.get((filing.gvkey, filing.cik, filing.fiscal_year), ())
    candidates = [row for row in candidates if row.accepted_at <= filing.accepted_at]
    if len(candidates) != 1:
        return np.nan, pd.NaT, (), filing.accepted_at
    interim = candidates[0]
    later_q3 = filings.loc[
        filings.gvkey.eq(filing.gvkey) & filings.cik.eq(filing.cik)
        & filings.period.eq(interim.period) & filings.form.eq("10-Q/A")
        & filings.accepted_at.between(interim.accepted_at, filing.accepted_at)
    ]
    if not later_q3.empty or filing.form != "10-K" or pd.isna(interim.income):
        return np.nan, pd.NaT, (), filing.accepted_at
    def facts(row):
        result = row._asdict()
        return dict(result, value=row.income, start=row.income_start, usable=row.accepted_at)
    result = fourth_quarter(facts(filing), facts(interim))
    if result is None or pd.isna(filing.income):
        return np.nan, pd.NaT, (), filing.accepted_at
    vendor = lookup.get((interim.gvkey, interim.period))
    if vendor is None or "niy" not in vendor:
        return np.nan, pd.NaT, (), filing.accepted_at
    matched = vendor.loc[(vendor.niy * 1e6).round(4).eq(interim.income)]
    if matched.empty:
        return np.nan, pd.NaT, (), filing.accepted_at
    vendor_at = matched.vintage.min().tz_localize("America/New_York") + pd.DateOffset(days=1)
    return result["value"], interim.period + pd.Timedelta(days=1), result["inputs"], max(
        result["usable"], vendor_at
    )


def reconcile_vintages(snapshots, contexts):
    """Pair exact USD values with independently verified filing contexts."""
    key_fields = ["gvkey", "cik", "accession"]
    supported = contexts.currency.eq("USD") & contexts.consolidated.eq(True) & (
        contexts.form.isin(["10-Q", "10-Q/A", "10-K", "10-K/A"])
    )
    rejects = contexts.loc[~supported, key_fields].assign(
        reason="unsupported_form_currency_or_basis").to_dict("records")
    filings = contexts.loc[supported].copy()
    fiscal = filings.fiscal_quarter
    valid_quarter = (
        (filings.form.str.startswith("10-K") & fiscal.eq(4))
        | (filings.form.str.startswith("10-Q") & fiscal.between(1, 3))
    )
    rejects.extend(filings.loc[~valid_quarter, key_fields].assign(
        reason="invalid_fiscal_quarter").to_dict("records"))
    filings = filings.loc[valid_quarter]
    if filings.duplicated(["gvkey", "cik", "accession", "income_type"]).any():
        raise ValueError("Duplicate independently verified accession context")
    nine = {}
    for row in filings.loc[filings.income_type.eq("nine_months") & filings.form.eq("10-Q")
                           & filings.fiscal_quarter.eq(3)
                           & (filings.period - filings.income_start).dt.days.between(255, 285)
                           ].itertuples(index=False):
        nine.setdefault((row.gvkey, row.cik, row.fiscal_year), []).append(row)
    lookup = {key: rows for key, rows in snapshots.groupby(["gvkey", "period"])}
    accepted = []
    primary_context = (
        (filings.form.str.startswith("10-K") & filings.income_type.eq("annual"))
        | (filings.form.str.startswith("10-Q") & filings.income_type.eq("quarter"))
    )
    for filing in filings.loc[primary_context].itertuples(index=False):
        rows = lookup.get((filing.gvkey, filing.period))
        key = {"gvkey": filing.gvkey, "cik": filing.cik, "accession": filing.accession}
        # A filing context receipt verifies parent equity and the preferred balance separately.
        book = filing.parent_equity - filing.preferred if filing.preferred_verified is True else np.nan
        if pd.notna(filing.preferred) and filing.preferred < 0:
            book = np.nan
        income, start, lineage, income_at = _filing_income(filing, filings, nine, lookup)
        duration = (filing.period - start).days
        if pd.notna(income) and not 80 <= duration <= 100:
            income, start, lineage = np.nan, pd.NaT, ()
            rejects.append(dict(key, reason="invalid_quarter_income_duration"))
        if rows is None:
            rejects.append(dict(key, reason="no_exact_vendor_period"))
            continue
        if not np.isfinite(filing.assets) or filing.assets <= 0:
            rejects.append(dict(key, reason="unverified_positive_assets"))
            continue
        rows = rows.loc[(rows.atq * 1e6).round(4).eq(filing.assets)
                        & pd.to_numeric(rows.fiscal_year_end).eq(filing.fiscal_year_end)].copy()
        if rows.empty:
            rejects.append(dict(key, reason="asset_or_fiscal_context_mismatch"))
            continue
        rows["income_ok"] = (rows.niq * 1e6).round(4).eq(income)
        rows["book_ok"] = (rows.ceqq * 1e6).round(4).eq(book)
        ordered = rows.sort_values("vintage")
        # An unverified later point date cannot erase an already corroborated original.
        # Record when each field first matched the same accession independently.
        first_income = ordered.loc[ordered.income_ok, "vintage"].min()
        first_book = ordered.loc[ordered.book_ok, "vintage"].min()
        if pd.isna(first_income):
            rejects.append(dict(key, reason="unverified_vendor_quarter_income"))
        if pd.isna(first_book):
            rejects.append(dict(key, reason="unverified_vendor_common_equity"))
        state = ordered[["income_ok", "book_ok"]].cummax()
        ordered[["income_ok", "book_ok"]] = state
        changes = state.ne(state.shift()).any(axis=1)
        for row in ordered.loc[changes].itertuples(index=False):
            accepted_at = max(filing.accepted_at, income_at) if row.income_ok else filing.accepted_at
            effective = filing_session(accepted_at.isoformat(), row.vintage.date().isoformat())
            if effective is None:
                rejects.append(dict(key, reason="outside_development_availability"))
                continue
            accepted.append(dict(
                key, fiscal_year=filing.fiscal_year, fiscal_quarter=filing.fiscal_quarter,
                fiscal_year_end=filing.fiscal_year_end, currency=filing.currency, basis=filing.basis,
                form=filing.form, period=filing.period, accepted_at=filing.accepted_at,
                usable=effective, vendor_date=row.vintage, source="wrds_snapshot",
                assets=filing.assets, net_income=income if row.income_ok else np.nan,
                income_vendor_date=first_income if row.income_ok else pd.NaT,
                book_vendor_date=first_book if row.book_ok else pd.NaT,
                net_income_start=start if row.income_ok else pd.NaT,
                net_income_accessions=lineage if row.income_ok else (),
                book_equity=book if row.book_ok else np.nan,
            ))
    return pd.DataFrame(accepted), pd.DataFrame(rejects)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path, help="Local export and provenance directory")
    parser.add_argument("output", type=Path, help="New local output directory")
    parser.add_argument("--snapshot-manifest", type=Path,
                        help="JSON array naming only the verified production WRDS batches")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true", help="Validate and assemble source records only")
    mode.add_argument("--review-receipt", type=Path, help="Claude clearance for the exact preflight")
    args = parser.parse_args()
    base = args.inputs
    if args.review_receipt:
        manifest_file = base / "preflight_manifest.json"
        receipt = json.loads(args.review_receipt.read_text())
        if receipt.get("reviewer") != "Claude" or receipt.get("decision") != "clear" or (
            receipt.get("preflight_sha256") != digest(manifest_file)
        ):
            raise ValueError("Full panel requires Claude clearance for this preflight manifest")
        manifest = json.loads(manifest_file.read_text())
        for name in ("panel_inputs.parquet", "vintages.parquet"):
            if manifest["outputs"].get(name) != digest(base / name):
                raise ValueError(f"Preflight artifact hash mismatch for {name}")
        if manifest["code_sha256"] != code_fingerprint():
            raise ValueError("Pipeline code changed after preflight")
        panel = build_features(pd.read_parquet(base / "panel_inputs.parquet"),
                               pd.read_parquet(base / "vintages.parquet"))
        args.output.mkdir(parents=True, exist_ok=False)
        panel.to_parquet(args.output / "fundamentals_panel.parquet", index=False)
        (args.output / "coverage.json").write_text(json.dumps(coverage(panel), indent=2))
        return
    roster_file = base / "roster.csv"
    if digest(roster_file) != ROSTER_SHA256:
        raise ValueError("Frozen roster hash mismatch")
    roster = pd.read_csv(roster_file, parse_dates=["signal", "prior_session"])
    if args.snapshot_manifest:
        entries = json.loads(args.snapshot_manifest.read_text())
        if not isinstance(entries, list) or not all(
            isinstance(name, str) and Path(name).name == name for name in entries
        ) or len(set(entries)) != len(entries):
            raise ValueError("Snapshot manifest requires unique local export basenames")
        snapshots = [base / name for name in entries]
    else:
        snapshots = sorted((*base.glob("snapshot_*.htm"), *base.glob("snapshot_*.html"),
                            *base.glob("snapshot_*.csv"), *base.glob("snapshot_*.csv.gz")))
    if not snapshots:
        raise ValueError("Missing WRDS browser snapshot exports")
    snapshot_conflicts = []
    vendor = load_snapshot(snapshots, quarantined=snapshot_conflicts)
    contexts_file = base / "verified_filing_contexts.parquet"
    contexts = pd.read_parquet(contexts_file)
    if contexts.accepted_at.gt(CALENDAR.session_close(END)).any() or contexts.period.gt(END).any():
        raise ValueError("Confirmation filing in context receipts")
    edgar_sources = validate_contexts(contexts, base / "edgar_metadata", base / "edgar_facts")
    paths = {}
    link_path = base / "links.parquet"
    if link_path.exists():
        paths["links"] = link_path
    ccm_exports = []
    if "links" not in paths:
        ccm_exports = sorted((*base.glob("ccm_*.csv.gz"), *base.glob("ccm_*.csv")))
        if not ccm_exports:
            raise ValueError("Missing historical CCM crosswalk exports")
    delisting_path = base / "delistings.parquet"
    if delisting_path.exists():
        paths["delistings"] = delisting_path
    delisting_exports = []
    if "delistings" not in paths:
        delisting_exports = sorted((*base.glob("crsp_delisting_*.csv.gz"), *base.glob("crsp_delisting_*.csv"),
                                   *base.glob("crsp_delisting_*.htm")))
        if not delisting_exports:
            raise ValueError("Missing development-period CRSP delisting exports")
    listing_path = base / "listing.parquet"
    if listing_path.exists():
        paths["listing"] = listing_path
    names_exports = []
    if "listing" not in paths:
        names_exports = sorted((*base.glob("crsp_names_*.csv.gz"), *base.glob("crsp_names_*.csv"),
                                *base.glob("crsp_names_*.htm")))
        if not names_exports:
            raise ValueError("Missing independently dated CRSP names exports")
    quote_path = base / "quotes.parquet"
    if quote_path.exists():
        paths["quotes"] = quote_path
    quote_exports = []
    if "quotes" not in paths:
        quote_exports = sorted((*base.glob("crsp_daily_*.htm"), *base.glob("crsp_daily_*.html"),
                                *base.glob("crsp_daily_*.csv"), *base.glob("crsp_daily_*.csv.gz")))
        if not quote_exports:
            raise ValueError("Missing CRSP prior-session quote exports")
    data = {name: pd.read_parquet(path) for name, path in paths.items()}
    if ccm_exports:
        data["links"] = load_ccm_links(ccm_exports, roster)
    if delisting_exports:
        data["delistings"] = load_crsp_delistings(delisting_exports)
    if names_exports:
        data["listing"] = load_crsp_names(names_exports)
    if quote_exports:
        data["quotes"] = load_crsp_daily(quote_exports, roster.prior_session)
    for field in ("start", "stop", "signal"):
        data["links"][field] = pd.to_datetime(data["links"][field], errors="raise")
        if data["links"][field].isna().any() or data["links"][field].gt(END).any():
            raise ValueError(f"Invalid development link {field}")
    vintages, rejected = reconcile_vintages(vendor, contexts)
    if vintages.empty:
        raise ValueError("No WRDS vintage reconciled to independently verified filings")
    originals = vintages.loc[vintages.form.isin(["10-Q", "10-K"])]
    anchors = originals[["gvkey", "cik", "period", "usable"]].drop_duplicates()
    linked = admit_links(roster, data["links"], anchors)
    ready = market_inputs(linked, data["listing"], data["quotes"], data["delistings"])
    args.output.mkdir(parents=True, exist_ok=False)
    tables = {"vintages": vintages, "quarantined": rejected, "panel_inputs": ready,
              "snapshot_conflicts": pd.DataFrame(snapshot_conflicts)}
    for name, table in tables.items():
        table.to_parquet(args.output / f"{name}.parquet", index=False)
    files = [roster_file, contexts_file, *snapshots, *paths.values(),
             *quote_exports, *names_exports, *delisting_exports, *ccm_exports, *edgar_sources]
    manifest = {"code_sha256": code_fingerprint(),
                "inputs": {path.relative_to(base).as_posix(): digest(path) for path in files},
                "outputs": {path.name: digest(path) for path in args.output.glob("*.parquet")}}
    if args.snapshot_manifest:
        manifest["snapshot_manifest_sha256"] = digest(args.snapshot_manifest)
    (args.output / "preflight_manifest.json").write_text(json.dumps(manifest, indent=2))


def code_fingerprint():
    directory = Path(__file__).resolve().parent
    return {
        name: digest(directory / name)
        for name in ("fundamentals_pipeline.py", "fundamentals_features.py",
                     "fundamentals_gate.py", "fundamentals_anchors.py")
    }


if __name__ == "__main__":
    main()
