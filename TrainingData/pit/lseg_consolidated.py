"""Download consolidated volume and closing bid/ask from LSEG consolidated RICs (run with the Python that
has lseg.data while LSEG Workspace is signed in).

Primary-listing RICs carry venue volume (~25-38% of consolidated). The consolidated line is:
  Nasdaq  XYZ.OQ[^S] -> XYZ.O[^S]       NYSE / other  XYZ.N[^S] -> XYZ[^S]
Verified 2026-11-20: AAPL.O and JPM volumes equal Alpha Vantage consolidated volume exactly.

  python TrainingData/pit/lseg_consolidated.py [--batch 10] [--resume DIR]
Writes indicators_data/lseg/consolidated/<UTC stamp>/batch_NNNN.csv + manifest.json (resumable).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lseg_deals import open_session  # noqa: E402

TRAINING_DATA = Path(__file__).resolve().parents[1]
FIELDS = ["ACVOL_UNS", "TRDPRC_1", "BID", "ASK"]


def consolidated_ric(ric: str) -> str:
    base, sep, suffix = ric.partition("^")
    name, dot, venue = base.rpartition(".")
    if not dot:
        return ric
    if venue in ("OQ", "O"):
        new = f"{name}.O"
    elif venue in ("N", "A", "P", "K"):
        new = name
    else:
        new = base
    return new + (sep + suffix if suffix else "")


def fallback_candidates(ric: str) -> list[str]:
    """Alternative consolidated RICs, tried in order when consolidated_ric() returns nothing.

    Verified 2026-11-20: for some NYSE names (ABBV, ORCL, CBRE, GRMN, NCLH) the bare RIC is not a valid universe
    and the consolidated line is XYZ.K; JPM.K / AAPL.K do not exist, so .K is only a fallback.
    """
    base, sep, suffix = ric.partition("^")
    name, dot, venue = base.rpartition(".")
    if not dot:
        name = base
    tail = sep + suffix if suffix else ""
    first = consolidated_ric(ric)
    out = []
    for c in (f"{name}.K{tail}", f"{name}{tail}", f"{name}.O{tail}"):
        if c != first and c not in out:
            out.append(c)
    return out


def missing_primary_rics(main_run: Path, sm: pd.DataFrame) -> list[str]:
    """Primary RICs whose main-run consolidated series has no volume at all."""
    man = json.loads((main_run / "manifest.json").read_text())
    have = set()
    for key, rec in man["batches"].items():
        if rec["status"] != "ok":
            continue
        raw = pd.read_csv(main_run / f"{key}.csv", header=[0, 1], index_col=0)
        for cons in rec["rics"]:
            if cons in raw.columns.get_level_values(0):
                v = pd.to_numeric(raw[cons].get("ACVOL_UNS"), errors="coerce")
                if v is not None and (v > 0).any():
                    have.add(cons)
    return sorted(r for r in sm[sm.role.eq("primary")].ric.unique() if consolidated_ric(r) not in have)


def run_fallback(ld, out: Path) -> None:
    """One request per candidate RIC (a bad RIC fails the whole batch); stop at the first candidate with volume."""
    sm = pd.read_csv(TRAINING_DATA / "indicators_data/pit/security_master.csv")
    main_run = sorted((TRAINING_DATA / "indicators_data/lseg/consolidated").glob("*"))[-1]
    out.mkdir(parents=True, exist_ok=True)
    man_path = out / "manifest.json"
    man = json.loads(man_path.read_text()) if man_path.exists() else {
        "fields": FIELDS, "main_run": main_run.name, "rics": {}}
    for ric in missing_primary_rics(main_run, sm):
        if man["rics"].get(ric, {}).get("status") in ("ok", "none"):
            continue
        rec = {"tried": []}
        for cand in fallback_candidates(ric):
            rec["tried"].append(cand)
            try:
                df = ld.get_history(cand, fields=FIELDS, start="2011-01-01", end="2026-11-18", interval="daily",
                                    adjustments="unadjusted")
            except Exception:
                continue
            if df is None or df.empty or not (pd.to_numeric(df.get("ACVOL_UNS"), errors="coerce") > 0).any():
                continue
            f = out / f"{cand.replace('^', '_')}.csv"
            df.to_csv(f, lineterminator="\n")
            rec.update(status="ok", cons_ric=cand, file=f.name, rows=int(len(df)),
                       sha256=hashlib.sha256(f.read_bytes()).hexdigest())
            break
        else:
            rec["status"] = "none"
        man["rics"][ric] = rec
        man_path.write_text(json.dumps(man, indent=2))
        print(ric, rec["status"], rec.get("cons_ric", ""), flush=True)
    ok = sum(1 for r in man["rics"].values() if r["status"] == "ok")
    print(json.dumps({"folder": str(out), "found": ok, "missing": len(man["rics"]) - ok}))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=10)
    ap.add_argument("--resume", type=Path)
    ap.add_argument("--fallback", action="store_true",
                    help="retry primary RICs with no consolidated data on alternative consolidated RICs")
    a = ap.parse_args()
    import lseg.data as ld
    logging.disable(logging.CRITICAL)
    if a.fallback:
        out = a.resume or TRAINING_DATA / "indicators_data/lseg/consolidated_fallback" / datetime.now(
            timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        s = open_session(ld)
        try:
            run_fallback(ld, out)
        finally:
            s.close()
        return
    sm = pd.read_csv(TRAINING_DATA / "indicators_data/pit/security_master.csv")
    rics = sorted(sm[sm.role.eq("primary")].ric.unique())
    pairs = [(r, consolidated_ric(r)) for r in rics]
    out = a.resume or TRAINING_DATA / "indicators_data/lseg/consolidated" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out.mkdir(parents=True, exist_ok=True)
    man_path = out / "manifest.json"
    man = json.loads(man_path.read_text()) if man_path.exists() else {"fields": FIELDS, "pairs": pairs, "batches": {}}
    s = open_session(ld)
    try:
        for i in range(0, len(pairs), a.batch):
            key = f"batch_{i:04d}"
            if man["batches"].get(key, {}).get("status") == "ok":
                continue
            chunk = [c for _, c in pairs[i:i + a.batch]]
            rec = {"rics": chunk}
            try:
                df = ld.get_history(chunk, fields=FIELDS, start="2011-01-01", end="2026-11-18", interval="daily",
                                    adjustments="unadjusted")
                f = out / f"{key}.csv"
                df.to_csv(f, lineterminator="\n")
                rec.update(status="ok", rows=int(len(df)), sha256=hashlib.sha256(f.read_bytes()).hexdigest())
            except Exception as e:
                rec.update(status="error", error=str(e)[:300])
            man["batches"][key] = rec
            man_path.write_text(json.dumps(man, indent=2))
            print(f"{key} {rec['status']}", flush=True)
    finally:
        s.close()
    ok = sum(1 for b in man["batches"].values() if b.get("status") == "ok")
    print(json.dumps({"folder": str(out), "batches_ok": ok, "batches_total": (len(pairs) + a.batch - 1) // a.batch}))


if __name__ == "__main__":
    main()
