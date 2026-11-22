"""Data-layer acceptance gate: evaluates every test in research/pit_data_2026-11-19_acceptance.md from the
builders' audit files and writes research/pit_data_acceptance_results.{json,md}.

  python -m pit.acceptance              # evaluate current artifacts (from TrainingData/)
  python -m pit.acceptance --rebuild    # R1: hash artifacts, rerun every builder, compare hashes, then evaluate

Thresholds are the preregistered ones; nothing here is tuned. P2 is reported as preregistered (FAIL on venue
volume) together with its logged amendments (P2a, consolidated re-test). K2 is reported, never pass/fail.
"""
from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import sys

import pandas as pd

from .config import LSEG_ROOT, OUTPUT, PROJECT_ROOT, TRAINING_DATA
from . import overrides
from .manifest import sha256

RESEARCH = PROJECT_ROOT / "research"
OVERRIDES = TRAINING_DATA / "pit" / "overrides"
# Builder order (each reads only earlier outputs, the LSEG snapshot and overrides). Network-free.
BUILDERS = ["identity", "membership", "prices", "settlement", "corporate_actions", "spreads", "consolidated"]
EXCLUSION_LIMIT = 0.005


def load(name: str) -> dict:
    return json.loads((OUTPUT / name).read_text())


def artifact_hashes() -> dict[str, str]:
    """Every pit/ artifact except manifests, which embed their creation time by design (their output hashes are
    covered because the outputs themselves are hashed here)."""
    return {p.name: sha256(p) for p in sorted(OUTPUT.iterdir())
            if p.is_file() and not p.name.endswith("_manifest.json")}


def rebuild() -> dict:
    before = artifact_hashes()
    for b in BUILDERS:
        r = subprocess.run([sys.executable, "-m", f"pit.{b}"], cwd=TRAINING_DATA, capture_output=True, text=True)
        if r.returncode != 0:
            return {"pass": False, "failed_builder": b, "stderr": r.stderr[-2000:]}
    after = artifact_hashes()
    diff = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    return {"pass": not diff, "artifacts": len(after), "differing": diff, "builders": BUILDERS}


def m3() -> dict:
    comp = json.loads((RESEARCH / "spy_roster_2010_comparison.json").read_text())["comparisons"][
        "ivv_2010-12-31_vs_replay_2011-01-03"]
    c = comp["counts"]
    after = comp["counts_after_sec_confirmation"]
    conf = overrides.load("roster_link_confirmations")
    open_replay = {r["isin"] for r in comp["only_in_replay"]}
    confirmed_isins = {x.get("replay_isin") for x in comp["sec_confirmation"]["confirmed"]}
    unlinked = open_replay - confirmed_isins          # still open after the SEC step
    review = after["linked_unconfirmed_review"]
    applied = conf[conf.replay_isin.isin(unlinked)]
    review_applied = conf[~conf.replay_isin.isin(unlinked)]
    missing_source = conf[(conf.source.str.strip() == "") | (conf.evidence.str.strip() == "")]
    linked = after["linked_total"] + len(applied)
    review_left = review - len(review_applied)
    ok = (linked == c["holding_lines"] == c["replay_isins"] and review_left == 0 and missing_source.empty
          and after["duplicate_replay_isins"] == 0 and conf.replay_isin.is_unique)
    return {"pass": bool(ok), "holding_lines": c["holding_lines"], "replay_isins": c["replay_isins"],
            "linked_after_sec": after["linked_total"], "manual_confirmations": conf[["ivv_line", "replay_isin"]].values.tolist(),
            "linked_final": linked, "review_tier_left": review_left,
            "source": "IVV N-Q 2010-12-31 (research/spy_roster_2010_comparison.md) + overrides/roster_link_confirmations.csv"}


def m5() -> dict:
    """Regression: the pipeline's membership equals the original replay candidate, row for row."""
    new = pd.read_csv(OUTPUT / "membership_pit.csv")
    with gzip.open(LSEG_ROOT / "20261119T132813190380Z" / "membership_dated_candidate.csv.gz", "rt") as f:
        old = pd.read_csv(f)
    key = [c for c in ("session", "isin") if c in new.columns]
    okey = [c for c in old.columns if c in ("session", "date")][:1] + [c for c in old.columns if c in ("isin", "ISIN")][:1]
    o = old[okey].set_axis(key, axis=1).astype(str)
    n = new[key].astype(str)
    j = n.merge(o, how="outer", indicator=True)
    extra, missing = int((j._merge == "left_only").sum()), int((j._merge == "right_only").sum())
    return {"pass": extra == 0 and missing == 0, "rows_new": len(n), "rows_old": len(o),
            "extra_rows": extra, "missing_rows": missing}


def evaluate(r1: dict | None) -> dict:
    mem, sm, px = load("membership_pit_audit.json"), load("security_master_audit.json"), load("prices_pit_audit.json")
    st, ca = load("settlement_pit_audit.json"), load("corporate_actions_audit.json")
    sp, co = load("spreads_pit_audit.json"), load("consolidated_pit_audit.json")
    probes = mem["boundary_probes"]
    unexplained = {d: p for d, p in probes.items() if p.get("unexplained_extra") or p.get("unexplained_missing")}
    t = {
        "M1": {"pass": all(not v["extra"] and not v["missing"] for v in mem["checkpoints"].values()),
               "checkpoints": mem["checkpoints"]},
        "M2": {"pass": not unexplained and all(a["ok"] for a in mem["probe_assertions"]),
               "probes": len(probes), "unexplained": unexplained,
               "assertions_failed": [a for a in mem["probe_assertions"] if not a["ok"]]},
        "M3": m3(),
        "M4": {"pass": not mem["forward_conflicts"] and not mem["reverse_conflicts"]
               and 495 <= mem["min_members"] and mem["max_members"] <= 510,
               "min_members": mem["min_members"], "max_members": mem["max_members"]},
        "M5": m5(),
        "I1": {"pass": bool(sm["pass"]), "securities": sm["securities"], "aliases": sm["aliases"]},
        "P1": {"pass": px["coverage"] >= 0.999, "coverage": px["coverage"]},
        "P2": {"pass": False, "preregistered_result": "FAIL (LSEG primary-RIC volume is venue volume)",
               "amendment_P2a_close_match_pass": px["P2a_pass"],
               "amendment_retest_consolidated_pass": co["P2_retest"]["pass"],
               "retest_share": co["P2_retest"]["share_passing_95pct_within_10pct"],
               "handling": "Volume is taken only from the consolidated series (amendment log 2026-11-20)."},
        "P3": {"pass": bool(px["P3_pass"]), "missing_not_in_ledger": px["missing_not_in_ledger"]},
        "C1": {"pass": bool(ca["C1_pass"]), "unverified": ca["C1_unverified"]},
        "C2": {"pass": bool(ca["C2"]["pass"]), "unexplained": ca["C2"]["unexplained"]},
        "C3": {"pass": bool(ca["C3_pass"]), "spy_dividends": ca["C3_spy_dividends"]},
        "S1": {"pass": bool(st["S1_pass"]), "needs_manual": st["needs_manual"]},
        "S2": {"pass": bool(st["S2_pass_with_documented_exceptions"]), "counts": st["S2_counts"],
               "undocumented": st["S2_undocumented"]},
        "K1": {"pass": sp["coverage"] >= 0.95, "coverage": sp["coverage"],
               "note": "Estimator is not fit for purpose (K2); the cost model uses quoted spreads."},
        "K2": {"reported_only": True, **co["K2"]},
        "R1": r1 or {"pass": None, "note": "not run; use --rebuild"},
    }
    # Completeness precondition of the downstream study (pit_nextopen amendment 2): every ever-member security
    # needs some consolidated volume and quotes, otherwise the ADV cap silently drops it.
    c = pd.read_parquet(OUTPUT / "consolidated_pit.parquet",
                        columns=["session", "isin", "volume_source", "quote_source"])
    p = pd.read_parquet(OUTPUT / "prices_pit.parquet", columns=["session", "isin", "member", "valid_bar"])
    m = p[p.member & p.valid_bar].merge(c, on=["session", "isin"], how="left")
    g = m.groupby("isin").agg(cons=("volume_source", lambda s: (s == "consolidated").any()),
                              scaled=("volume_source", lambda s: (s == "venue_scaled").any()),
                              q=("quote_source", lambda s: (s == "consolidated").any()))
    covered = (g.cons & g.q) | (~g.cons & g.scaled)      # documented fallback: venue-scaled volume + estimator spread
    none = g[~covered]
    t["completeness"] = {"pass": none.empty, "securities_uncovered": none.index.tolist(),
                         "securities_on_fallback": int((~g.cons & g.scaled).sum()),
                         "fallback_member_session_share": round(float((m.volume_source == "venue_scaled").mean()), 5),
                         "no_volume_member_session_share": round(float((m.volume_source == "none").mean()), 5),
                         "note": "Precondition of pit_nextopen (strict load), not a preregistered data test."}
    required = [k for k in t if k not in ("K2", "P2", "completeness")]
    failed = [k for k in required if t[k].get("pass") is not True]
    # P2 is a recorded failure handled by amendment: accepted only if both amendment checks pass.
    p2_handled = t["P2"]["amendment_P2a_close_match_pass"] and t["P2"]["amendment_retest_consolidated_pass"]
    if not p2_handled:
        failed.append("P2")
    verdict = "ACCEPTED" if not failed else "NOT ACCEPTED"
    return {"verdict": verdict, "failed": failed, "p2_handled_by_amendment": bool(p2_handled), "tests": t}


def write_report(res: dict) -> None:
    (RESEARCH / "pit_data_acceptance_results.json").write_text(json.dumps(res, indent=2, default=str))
    L = ["# Point-in-time data layer: acceptance results", "",
         "Generated by `python -m pit.acceptance` against the preregistered tests in "
         "`pit_data_2026-11-19_acceptance.md`. Raw values: `pit_data_acceptance_results.json`.", "",
         f"**Verdict: {res['verdict']}**" + (f" (failing: {', '.join(res['failed'])})" if res["failed"] else ""), "",
         "| Test | Result | Key figures |", "|---|---|---|"]
    for k, v in res["tests"].items():
        if k == "K2":
            r = "reported"
            fig = f"quoted 21d median {v['quoted_21d_median_p10_p50_p90'][1]:.5f}, estimate {v['estimate_median']:.5f}"
        elif k == "P2":
            r = "FAIL (preregistered), handled by amendment" if res["p2_handled_by_amendment"] else "FAIL"
            fig = f"P2a {v['amendment_P2a_close_match_pass']}, consolidated re-test {v['retest_share']:.1%}"
        else:
            r = {True: "PASS", False: "FAIL", None: "not run"}[v.get("pass")]
            fig = ", ".join(f"{a}={b}" for a, b in v.items() if a != "pass" and isinstance(b, (int, float, str))
                            and not isinstance(b, bool))[:160]
        L.append(f"| {k} | {r} | {fig} |")
    (RESEARCH / "pit_data_acceptance_results.md").write_text("\n".join(L) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()
    r1 = rebuild() if a.rebuild else None
    res = evaluate(r1)
    write_report(res)
    print(json.dumps({"verdict": res["verdict"], "failed": res["failed"],
                      "completeness": {k: v for k, v in res["tests"]["completeness"].items()
                                       if k != "securities_uncovered"}}, default=str))


if __name__ == "__main__":
    main()
