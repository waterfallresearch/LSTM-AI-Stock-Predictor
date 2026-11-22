"""Freeze and verify the independent filing review for a fundamentals preflight."""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
import re

import pandas as pd

from TrainingData.pit.fundamentals_features import assess_gate, freeze_audit_sample
from TrainingData.pit.fundamentals_pipeline import compact_snapshot_batches, digest
from TrainingData.pit.sec_statement_audit import check_vintage_numbers, observed_fact


def audit_frame(vintages, panel_inputs, rejected):
    """Choose one auditable use per issuer accession before the review reads values."""
    key = ["gvkey", "cik", "accession"]
    candidates = vintages.loc[
        vintages[["assets", "net_income", "book_equity"]].notna().all(axis=1),
        key + ["form", "period", "usable"],
    ].drop_duplicates()
    month_cols = ["gvkey", "cik", "signal", "prior_session", "permno", "permco",
                  "start", "stop", "size_tercile", "delist_date"]
    available = panel_inputs.loc[panel_inputs.cap.notna(), month_cols]
    uses = candidates.merge(available, on=["gvkey", "cik"])
    uses = uses.loc[
        uses.usable.le(uses.prior_session)
        & uses.period.between(pd.to_datetime(uses.start), pd.to_datetime(uses.stop))
        & (uses.signal - uses.period).dt.days.between(0, 180)
    ].sort_values(["signal", "permno", "usable"])
    accepted = uses.drop_duplicates(key).assign(disposition="accepted", reason="verified_candidate")
    accepted["stratum"] = (accepted.form + "|" + accepted.signal.dt.year.astype(str) + "|"
                           + accepted.size_tercile.fillna(0).astype(int).astype(str))
    # An accession can be admitted with all fields on a later date. Classify
    # each accession only once across the two audit populations.
    bad = rejected.dropna(subset=key)[key + ["reason"]].sort_values("reason").drop_duplicates(key)
    bad = bad.merge(accepted[key].assign(admitted=True), on=key, how="left")
    bad = bad.loc[bad.admitted.isna()].drop(columns="admitted")
    known_forms = vintages[key + ["form"]].drop_duplicates()
    known_forms = known_forms.loc[~known_forms.duplicated(key, keep=False)]
    bad = bad.merge(known_forms, on=key, how="left", validate="one_to_one")
    bad = bad.assign(disposition="rejected", stratum=bad.form.fillna("unresolved") + "|" + bad.reason)
    frame = pd.concat([accepted, bad], ignore_index=True)
    frame["audit_id"] = frame[key].astype(str).agg("|".join, axis=1)
    frame["mandatory"] = False
    for selector in (
        accepted.form.isin(["10-K", "10-Q"]),
        accepted.form.isin(["10-K/A", "10-Q/A"]),
        accepted.delist_date.gt(accepted.signal),
    ):
        reference = accepted.loc[selector, key]
        if not reference.empty:
            reference = reference.sort_values(key).iloc[0]
            audit_id = "|".join(str(reference[col]) for col in key)
            frame.loc[frame.audit_id.eq(audit_id), "mandatory"] = True
    if not accepted.form.isin(["10-K/A", "10-Q/A"]).any():
        amendments = bad.loc[bad.form.isin(["10-K/A", "10-Q/A"]), key]
        if not amendments.empty:
            reference = amendments.sort_values(key).iloc[0]
            frame.loc[frame.audit_id.eq("|".join(str(reference[col]) for col in key)), "mandatory"] = True
    return frame


def independent_cap(expected, quotes):
    """Recompute a sampled issuer's market cap from share counts in thousands."""
    expected = set(expected)
    if not expected or quotes.permno.duplicated().any() or set(quotes.permno) != expected:
        return None
    total = Decimal(0)
    for row in quotes.itertuples(index=False):
        price, thousands = Decimal(str(row.price)), Decimal(str(row.shrout))
        if not price.is_finite() or not thousands.is_finite() or price <= 0 or thousands <= 0:
            return None
        total += price * thousands * 1000
    return total


def _preflight_frames(preflight):
    manifest_path = preflight / "preflight_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    frames = {}
    for name in ("vintages", "panel_inputs", "quarantined"):
        path = preflight / f"{name}.parquet"
        if manifest["outputs"].get(path.name) != digest(path):
            raise ValueError(f"Preflight audit input hash mismatch for {name}")
        frames[name] = pd.read_parquet(path)
    return manifest_path, frames


def check_accepted_xbrl(sample, vintages, indices, instances, sample_sha256):
    """Produce independent machine evidence for accepted accessions only."""
    rows = []
    for item in sample.loc[sample.disposition.eq("accepted")].itertuples(index=False):
        candidate = vintages.loc[
            vintages.accession.eq(item.accession) & vintages.cik.eq(item.cik)
            & vintages.gvkey.eq(item.gvkey) & vintages.period.eq(item.period)
            & vintages.usable.eq(item.usable)
            & vintages[["assets", "net_income", "book_equity"]].notna().all(axis=1)
        ]
        index = indices.get(item.accession, {})
        document = instances.get(item.accession, {})
        problems = []
        if len(candidate) != 1:
            problems.append("missing_or_ambiguous_frozen_vintage")
        else:
            vintage = next(candidate.itertuples(index=False))
            if not index.get("accepted_et") or pd.Timestamp(index["accepted_et"]).tz_localize(
                "America/New_York"
            ) != vintage.accepted_at:
                problems.append("index_acceptance")
            if index.get("cik") != item.cik or index.get("report_period") != item.period.date().isoformat():
                problems.append("index_identity_or_period")
            facts = document.get("facts", [])
            # Compustat labels Jan–May year ends with the preceding calendar year.
            # This converts the label for independent comparison without changing dates.
            sec_year = vintage.fiscal_year + int(1 <= vintage.fiscal_year_end <= 5)
            for tag, expected, issue in (
                ("DocumentFiscalYearFocus", str(sec_year), "document_fiscal_year"),
                ("DocumentFiscalPeriodFocus", {1: "Q1", 2: "Q2", 3: "Q3", 4: "FY"}[vintage.fiscal_quarter],
                 "document_fiscal_quarter"),
            ):
                if {fact["value"] for fact in facts if fact["tag"] == tag} != {expected}:
                    problems.append(issue)
            forms = {fact["value"] for fact in facts if fact["tag"] == "DocumentType"}
            amendment_confirmed = (
                vintage.form.endswith("/A") and forms == {vintage.form.removesuffix("/A")}
                and index.get("index_form") == vintage.form
            )
            if forms != {vintage.form} and not amendment_confirmed:
                problems.append("document_form")
            problems.extend(check_vintage_numbers(vintage, instances))
        evidence = json.dumps({
            "index": index.get("url"), "index_sha256": index.get("sha256"),
            "instance": document.get("instance_url"), "instance_sha256": document.get("instance_sha256"),
            "unresolved": problems,
        })
        rows.append({"audit_id": item.audit_id, "resolved": not problems, "evidence": evidence,
                     "sample_sha256": sample_sha256})
    return pd.DataFrame(rows)


def check_rejected_xbrl(sample, vendor, contexts, indices, instances, sample_sha256):
    """Challenge the frozen rejection reason against a separate SEC instance."""
    rows = []
    for item in sample.loc[sample.disposition.eq("rejected")].itertuples(index=False):
        index = indices.get(item.accession, {})
        document = instances.get(item.accession, {})
        problems = []
        support = None
        context = contexts.loc[
            contexts.accession.eq(item.accession) & ~contexts.income_type.eq("nine_months")
        ]
        if len(context) != 1 or not index.get("report_period") or not document.get("instance_sha256"):
            problems.append("missing_source_or_original_filing")
        else:
            fiscal = next(context.itertuples(index=False))
            day = index["report_period"]
            if fiscal.period.date().isoformat() != day or index.get("cik") != item.cik or (
                not index.get("accepted_et") or pd.Timestamp(index["accepted_et"]).tz_localize(
                    "America/New_York"
                ) != fiscal.accepted_at
            ):
                problems.append("index_identity_period_or_acceptance")
            raw = vendor.loc[vendor.gvkey.eq(item.gvkey) & vendor.period.eq(fiscal.period)]
            assets = observed_fact(document, "Assets", day)
            asset_matches = (
                (raw.atq * 1_000_000).round(4).eq(float(assets[0]))
                & pd.to_numeric(raw.fiscal_year_end).eq(fiscal.fiscal_year_end)
            ) if assets else pd.Series(False, index=raw.index)
            matched = raw.loc[asset_matches]
            if item.reason == "unverified_positive_assets" and (assets is None or assets[0] <= 0):
                support = "original_filing_has_no_unique_positive_total_assets"
            if item.reason == "asset_or_fiscal_context_mismatch" and assets and matched.empty:
                support = "no_exact_vendor_asset_and_fiscal_context_match"
            if item.reason == "unverified_vendor_common_equity":
                stock = observed_fact(document, "StockholdersEquity", day)
                carrying = observed_fact(document, "PreferredStockCarryingValue", day)
                outstanding = observed_fact(document, "PreferredStockSharesOutstanding", day, unit="shares")
                issued = observed_fact(document, "PreferredStockSharesIssued", day, unit="shares")
                other = [observed_fact(document, tag, day) for tag in (
                    "PreferredStockValue", "PreferredStockRedemptionAmount", "PreferredStockRedemptionValue",
                    "PreferredStockLiquidationPreferenceValue",
                )]
                if carrying is None and outstanding and outstanding[0] == 0 and (
                    issued is None or issued[0] == 0
                ) and all(value is None or value[0] == 0 for value in other):
                    carrying = (Decimal(0), Decimal(0), None)
                if not stock or not carrying:
                    support = "original_filing_lacks_unambiguous_common_equity_basis"
                elif not (matched.ceqq.mul(1_000_000).round(4).eq(float(stock[0] - carrying[0]))).any():
                    support = "no_exact_vendor_common_equity_match"
            if item.reason == "unverified_vendor_quarter_income" and fiscal.fiscal_quarter in (1, 2, 3):
                income = observed_fact(document, "NetIncomeLoss", day, duration=(80, 100))
                if income is None:
                    support = "no_unique_original_quarter_income"
                elif not (matched.niq.mul(1_000_000).round(4).eq(float(income[0]))).any():
                    support = "no_exact_vendor_quarter_income_match"
        if not support:
            problems.append("rejection_reason_not_independently_corroborated")
        evidence = json.dumps({
            "index": index.get("url"), "index_sha256": index.get("sha256"),
            "instance": document.get("instance_url"), "instance_sha256": document.get("instance_sha256"),
            "corroboration": support, "unresolved": problems,
        })
        rows.append({"audit_id": item.audit_id, "resolved": not problems, "evidence": evidence,
                     "sample_sha256": sample_sha256})
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("preflight", type=Path)
    parser.add_argument("audit_dir", type=Path)
    parser.add_argument("--evidence-manifest-sha256",
                        help="Reviewed hash of audit_dir/sec_evidence_manifest.json")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--freeze", action="store_true")
    mode.add_argument("--check-accepted", action="store_true")
    mode.add_argument("--check-rejected", action="store_true")
    mode.add_argument("--finalize", nargs=3, type=Path, metavar=("COVERAGE", "AUDIT_RECEIPTS", "CAP_EVIDENCE"))
    args = parser.parse_args()
    manifest, frames = _preflight_frames(args.preflight)
    sample_path = args.audit_dir / "frozen_sample.parquet"
    seal_path = args.audit_dir / "sample_manifest.json"
    if args.freeze:
        frame = audit_frame(frames["vintages"], frames["panel_inputs"], frames["quarantined"])
        selected = freeze_audit_sample(frame)
        sample = selected.merge(frame.drop(columns=["disposition", "stratum", "mandatory"]),
                                on="audit_id", validate="one_to_one")
        args.audit_dir.mkdir(exist_ok=False, parents=True)
        sample.to_parquet(sample_path, index=False)
        seal = {"preflight_sha256": digest(manifest), "sample_sha256": digest(sample_path),
                "audit_code_sha256": digest(Path(__file__))}
        seal_path.write_text(json.dumps(seal, indent=2))
        return
    seal = json.loads(seal_path.read_text())
    if seal["preflight_sha256"] != digest(manifest) or seal["sample_sha256"] != digest(sample_path):
        raise ValueError("Frozen audit sample or preflight changed")
    sample = pd.read_parquet(sample_path)
    if seal["audit_code_sha256"] != digest(Path(__file__)):
        if args.finalize:
            raise ValueError("Finalization requires the frozen audit code")
        frame = audit_frame(frames["vintages"], frames["panel_inputs"], frames["quarantined"])
        selected = freeze_audit_sample(frame)
        if not sample[selected.columns].equals(selected):
            raise ValueError("Current sampler cannot reproduce the frozen sample")
    if args.check_accepted or args.check_rejected:
        evidence_manifest = args.audit_dir / "sec_evidence_manifest.json"
        if not args.evidence_manifest_sha256 or digest(evidence_manifest) != args.evidence_manifest_sha256:
            raise ValueError("Filing checks require the reviewed SEC evidence manifest hash")
        entries = json.loads(evidence_manifest.read_text())
        evidence_paths = sorted(args.audit_dir.glob("sec_instance_*.json"))
        if not evidence_paths:
            raise ValueError("No original SEC instance evidence is available")
        index_path = args.audit_dir / "sec_filing_indices.json"
        supplemental = args.audit_dir / "sec_index_forms.json"
        evidence_paths_to_verify = [index_path, *evidence_paths]
        if supplemental.exists():
            evidence_paths_to_verify.append(supplemental)
        if set(entries) != {path.name for path in evidence_paths_to_verify}:
            raise ValueError("SEC evidence files differ from the reviewed manifest")
        for path in evidence_paths_to_verify:
            if digest(path) != entries[path.name]:
                raise ValueError(f"SEC evidence hash mismatch: {path.name}")
        indices = {row["accession"]: row for row in json.loads(
            index_path.read_text()
        )}
        if supplemental.exists():
            for row in json.loads(supplemental.read_text()):
                existing = indices[row["accession"]]
                if (row["sha256"] != existing["sha256"] or row["url"] != existing["url"]):
                    raise ValueError("Supplemental index form evidence differs from frozen SEC response")
                raw_index = args.audit_dir / f"sec_index_{row['accession']}.htm"
                if digest(raw_index) != existing["sha256"]:
                    raise ValueError("Original SEC index bytes differ from the frozen SEC response")
                form = re.search(r'id="formName">\s*<strong>Form\s+(10-[QK](?:/A)?)</strong>',
                                 raw_index.read_text(encoding="utf-8"))
                if form is None or form[1] != row["index_form"]:
                    raise ValueError("Supplemental form disagrees with the original SEC index")
                existing["index_form"] = form[1]
        records = {}
        for path in evidence_paths:
            for row in json.loads(path.read_text()):
                if row["accession"] in records:
                    raise ValueError("Duplicate original SEC instance evidence")
                records[row["accession"]] = row
        if args.check_accepted:
            disposition = "accepted"
            result = check_accepted_xbrl(sample, frames["vintages"], indices, records, seal["sample_sha256"])
        else:
            disposition = "rejected"
            inputs = json.loads(manifest.read_text())["inputs"]
            source = args.preflight.parent
            names = [name for name in inputs if name.startswith("snapshot_") or name == "verified_filing_contexts.parquet"]
            for name in names:
                if digest(source / name) != inputs[name]:
                    raise ValueError(f"Reviewed rejection input changed: {name}")
            contexts = pd.read_parquet(source / "verified_filing_contexts.parquet")
            vendor = compact_snapshot_batches([source / name for name in names if name.startswith("snapshot_")], [])
            result = check_rejected_xbrl(sample, vendor, contexts, indices, records, seal["sample_sha256"])
        evidence_path = args.audit_dir / f"{disposition}_xbrl_evidence.parquet"
        if evidence_path.exists():
            raise ValueError("Audit evidence already exists")
        result.to_parquet(evidence_path, index=False)
        print(json.dumps({"disposition": disposition, "rows": len(result), "resolved": int(result.resolved.sum()),
                          "sha256": digest(evidence_path)}, indent=2))
        return
    coverage_path, audit_path, cap_path = args.finalize
    metrics = json.loads(coverage_path.read_text())
    if metrics.get("preflight_sha256") != seal["preflight_sha256"]:
        raise ValueError("Coverage refers to a different reviewed preflight")
    if metrics.get("panel_sha256") != digest(coverage_path.parent / "fundamentals_panel.parquet"):
        raise ValueError("Coverage panel bytes changed")
    receipts = pd.read_parquet(audit_path)
    if not receipts.sample_sha256.eq(seal["sample_sha256"]).all():
        raise ValueError("Audit receipts refer to a different sample")
    if receipts.evidence.isna().any() or receipts.evidence.str.strip().eq("").any():
        raise ValueError("Audit receipts require independent source evidence")
    checks = pd.read_parquet(cap_path)[["prior_session", "permco", "independent_cap"]]
    production = frames["panel_inputs"][["prior_session", "permco", "cap"]].dropna().drop_duplicates()
    comparisons = sample[["audit_id", "prior_session", "permco"]].merge(
        checks, on=["prior_session", "permco"], how="left", validate="many_to_one"
    ).merge(production, on=["prior_session", "permco"], how="left", validate="many_to_one")
    errors = comparisons.independent_cap / comparisons.cap - 1
    bound = comparisons[["audit_id"]].assign(cap_error=errors)
    receipts = receipts.drop(columns="cap_error", errors="ignore").merge(
        bound, on="audit_id", how="left", validate="one_to_one"
    )
    decision = assess_gate(metrics, receipts, sample)
    print(json.dumps(dict(decision, audit_sha256=digest(audit_path),
                          coverage_sha256=digest(coverage_path), independent_cap_sha256=digest(cap_path)),
                     indent=2))


if __name__ == "__main__":
    main()
