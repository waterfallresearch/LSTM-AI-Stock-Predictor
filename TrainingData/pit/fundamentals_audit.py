"""Freeze and verify the independent filing review for a fundamentals preflight."""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path

import pandas as pd

from TrainingData.pit.fundamentals_features import assess_gate, freeze_audit_sample
from TrainingData.pit.fundamentals_pipeline import digest


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("preflight", type=Path)
    parser.add_argument("audit_dir", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--freeze", action="store_true")
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
    if seal["audit_code_sha256"] != digest(Path(__file__)):
        raise ValueError("Audit code changed after the sample was frozen")
    coverage_path, audit_path, cap_path = args.finalize
    metrics = json.loads(coverage_path.read_text())
    if metrics.get("preflight_sha256") != seal["preflight_sha256"]:
        raise ValueError("Coverage refers to a different reviewed preflight")
    if metrics.get("panel_sha256") != digest(coverage_path.parent / "fundamentals_panel.parquet"):
        raise ValueError("Coverage panel bytes changed")
    receipts = pd.read_parquet(audit_path)
    sample = pd.read_parquet(sample_path)
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
