"""Consolidated volume and closing bid/ask per security-session, plus acceptance re-test P2 and test K2.

Input: indicators_data/lseg/consolidated/<stamp>/ (pit/lseg_consolidated.py), mapped back to securities
through the primary RIC each consolidated RIC was derived from and the dated security master.
Output: indicators_data/pit/consolidated_pit.parquet
  session, isin, volume_consolidated, close_consolidated, bid, ask, quoted_spread ((ask-bid)/mid)

P2 (re-test, consolidated series): volume within +/-10% of Alpha Vantage consolidated volume on >= 95% of
  overlapping sessions, per security with a local Alpha Vantage file.
K2: estimated spread (pit.spreads 21-day median) vs 21-day median quoted closing spread; error reported.

Usage: python -m pit.consolidated   (from TrainingData/)
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .config import LSEG_ROOT, OUTPUT, TRAINING_DATA
from .manifest import write_manifest


def load_raw() -> tuple[pd.DataFrame, list]:
    run = sorted((LSEG_ROOT / "consolidated").glob("*"))[-1]
    man = json.loads((run / "manifest.json").read_text())
    back = {c: p for p, c in man["pairs"]}
    frames, files = [], []
    for key, rec in sorted(man["batches"].items()):
        if rec["status"] != "ok":
            continue
        f = run / f"{key}.csv"
        files.append(f)
        raw = pd.read_csv(f, header=[0, 1], index_col=0)
        for cons in rec["rics"]:
            if cons not in raw.columns.get_level_values(0):
                continue
            b = raw[cons].apply(pd.to_numeric, errors="coerce").dropna(how="all")
            if b.empty:
                continue
            frames.append(pd.DataFrame({"session": b.index.astype(str).str[:10], "ric": back[cons], "cons_ric": cons,
                                        "volume_consolidated": b.get("ACVOL_UNS"), "close_consolidated": b.get("TRDPRC_1"),
                                        "bid": b.get("BID"), "ask": b.get("ASK")}))
    main = pd.concat(frames, ignore_index=True)
    # Fallback run (lseg_consolidated.py --fallback): alternative consolidated RICs (e.g. XYZ.K) for primary RICs
    # whose standard consolidated RIC returned nothing. Replaces any main-run rows for those primary RICs.
    fb_runs = sorted((LSEG_ROOT / "consolidated_fallback").glob("*"))
    if fb_runs:
        fb = fb_runs[-1]
        fman = json.loads((fb / "manifest.json").read_text())
        fb_frames = []
        for ric, rec in sorted(fman["rics"].items()):
            if rec.get("status") != "ok":
                continue
            f = fb / rec["file"]
            files.append(f)
            b = pd.read_csv(f, index_col=0).apply(pd.to_numeric, errors="coerce").dropna(how="all")
            fb_frames.append(pd.DataFrame({"session": b.index.astype(str).str[:10], "ric": ric, "cons_ric": rec["cons_ric"],
                                           "volume_consolidated": b.get("ACVOL_UNS"), "close_consolidated": b.get("TRDPRC_1"),
                                           "bid": b.get("BID"), "ask": b.get("ASK")}))
        if fb_frames:
            fbd = pd.concat(fb_frames, ignore_index=True)
            main = pd.concat([main[~main.ric.isin(set(fbd.ric))], fbd], ignore_index=True)
    return main, files


RATIO_WINDOW = 63  # sessions; trailing median of the daily cross-sectional consolidated/venue ratio


def venue_code(ric: pd.Series) -> pd.Series:
    return ric.str.split("^").str[0].str.rsplit(".", n=1).str[-1]


def add_volume_fallback(m: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """volume_adv: consolidated volume where it exists, else venue volume x the trailing (<= t) median
    consolidated/venue ratio of OTHER securities on the same listing venue. volume_source says which.

    Used for securities whose consolidated RIC LSEG cannot serve (mostly bankrupt or failed names, which must not be
    dropped: dropping them re-introduces survivorship bias). Accuracy is measured out of sample on securities that do
    have consolidated volume: the scaled estimate is compared with the true consolidated value, per session.
    """
    m = m.copy()
    m["venue"] = venue_code(m.ric)
    both = m[(m.volume_consolidated > 0) & (m.volume_venue > 0) & m.valid_bar]
    daily = (both.volume_consolidated / both.volume_venue).groupby([both.venue, both.session]).median()
    ratio = (daily.groupby(level=0, group_keys=False)
             .apply(lambda s: s.sort_index(level=1).rolling(RATIO_WINDOW, min_periods=10).median())
             .rename("venue_ratio").reset_index())
    m = m.merge(ratio, on=["venue", "session"], how="left")
    has = m.volume_consolidated > 0
    scaled = m.volume_venue * m.venue_ratio
    m["volume_adv"] = np.where(has, m.volume_consolidated, np.where(scaled > 0, scaled, np.nan))
    m["volume_source"] = np.where(has, "consolidated", np.where(scaled > 0, "venue_scaled", "none"))
    # out-of-sample accuracy of the scaling on sessions where the truth is known
    chk = m[has & (scaled > 0) & m.member & m.valid_bar]
    err = np.log(scaled[chk.index] / chk.volume_consolidated)
    # same check on 21-session ADV (what the cost model uses)
    t = chk.sort_values(["isin", "session"])
    adv_true = t.groupby("isin").volume_consolidated.transform(lambda s: s.rolling(21, min_periods=10).mean())
    adv_est = (t.volume_venue * t.venue_ratio).groupby(t["isin"]).transform(lambda s: s.rolling(21, min_periods=10).mean())
    e21 = np.log(adv_est / adv_true).dropna()
    audit = {"ratio_window_sessions": RATIO_WINDOW,
             "venue_ratio_median_by_venue": {k: round(float(v), 3) for k, v in daily.groupby(level=0).median().items()},
             "daily_abs_log_error_median": round(float(err.abs().median()), 4),
             "adv21_abs_log_error_median": round(float(e21.abs().median()), 4),
             "adv21_within_25pct": round(float((e21.abs() <= np.log(1.25)).mean()), 4),
             "adv21_within_50pct": round(float((e21.abs() <= np.log(1.5)).mean()), 4)}
    return m.drop(columns=["venue", "venue_ratio"]), audit


def main() -> None:
    raw, files = load_raw()
    px = pd.read_parquet(OUTPUT / "prices_pit.parquet",
                         columns=["session", "isin", "ric", "close", "volume_venue", "valid_bar", "member"])
    m = px.merge(raw, on=["ric", "session"], how="left")
    mid = (m.bid + m.ask) / 2
    m["quoted_spread"] = np.where((m.bid > 0) & (m.ask >= m.bid), (m.ask - m.bid) / mid, np.nan)
    m, fb_audit = add_volume_fallback(m)
    m["quote_source"] = np.where(np.isfinite(m.quoted_spread), "consolidated", "none")
    out = m[["session", "isin", "ric", "cons_ric", "volume_consolidated", "close_consolidated", "bid", "ask", "quoted_spread",
             "volume_adv", "volume_source", "quote_source"]]
    out_path = OUTPUT / "consolidated_pit.parquet"
    out.to_parquet(out_path, index=False)

    mem = m[m.member & m.valid_bar]
    cov_vol = float((mem.volume_consolidated > 0).mean())
    cov_q = float(np.isfinite(mem.quoted_spread).mean())
    close_match = float(((mem.close_consolidated / mem.close - 1).abs() < 1e-4).mean())

    # P2 re-test against local Alpha Vantage files (consolidated volume), per security
    av_dir = TRAINING_DATA / "indicators_data" / "raw" / "stocksData"
    per = []
    for isin, d in mem.groupby("isin"):
        tk = d.ric.iloc[-1].split(".")[0].split("^")[0]
        f = av_dir / f"{tk}_daily.csv"
        if "^" in d.ric.iloc[-1] or not f.exists():
            continue  # expired RICs: AV ticker may belong to another company
        av = pd.read_csv(f, usecols=["date", "close", "volume"]).rename(columns={"date": "session"})
        j = d.merge(av, on="session", how="inner", suffixes=("", "_av"))
        j = j[(j.volume > 0) & (j.volume_consolidated > 0) & ((j.close / j.close_av - 1).abs() < 1e-3)]
        if len(j) < 60:
            continue
        r = j.volume_consolidated / j.volume
        per.append({"isin": isin, "ticker": tk, "sessions": len(j), "median_ratio": float(r.median()),
                    "within_10pct": float(((r - 1).abs() <= 0.10).mean())})
    per = pd.DataFrame(per)
    p2_share = float((per.within_10pct >= 0.95).mean()) if len(per) else float("nan")

    # K2: estimated vs quoted spread (21-session medians)
    sp = pd.read_parquet(OUTPUT / "spreads_pit.parquet")
    q = m[m.valid_bar].sort_values(["isin", "session"])[["session", "isin", "quoted_spread"]].copy()
    q["quoted_21d"] = q.groupby("isin").quoted_spread.transform(lambda s: s.rolling(21, min_periods=10).median())
    k = q.merge(sp, on=["session", "isin"]).merge(mem[["session", "isin"]], on=["session", "isin"])
    k = k[np.isfinite(k.quoted_21d) & np.isfinite(k.spread_est)]
    err = k.spread_est - k.quoted_21d
    audit = {
        "member_sessions": int(len(mem)), "consolidated_volume_coverage": round(cov_vol, 5),
        "quoted_spread_coverage": round(cov_q, 5), "consolidated_close_matches_primary_close": round(close_match, 5),
        "volume_fallback": {**fb_audit,
                            "member_session_share_by_source": mem.volume_source.value_counts(normalize=True).round(5).to_dict(),
                            "securities_venue_scaled_only": sorted(mem.groupby("isin").volume_source.agg(
                                lambda s: (s != "consolidated").all()).loc[lambda s: s].index.tolist()),
                            "quote_note": "No quotes for venue_scaled securities: the cost model falls back to the "
                                          "daily-bar estimator, which overstates S&P 500 spreads ~10x (conservative)."},
        "P2_retest": {"securities_compared": int(len(per)), "share_passing_95pct_within_10pct": round(p2_share, 4),
                      "median_ratio_p10_p50_p90": per.median_ratio.quantile([.1, .5, .9]).round(4).tolist() if len(per) else [],
                      "pass": bool(p2_share >= 0.95), "worst": per.nsmallest(8, "within_10pct").round(4).to_dict("records")},
        "K2": {"sessions": int(len(k)), "quoted_21d_median_p10_p50_p90": k.quoted_21d.quantile([.1, .5, .9]).round(5).tolist(),
               "estimate_median": round(float(k.spread_est.median()), 5),
               "median_abs_error": round(float(err.abs().median()), 5), "median_error": round(float(err.median()), 5),
               "rank_corr_by_security": round(float(k.groupby("isin")[["spread_est", "quoted_21d"]].median().corr("spearman").iloc[0, 1]), 4),
               "note": "Reported, not pass/fail (preregistered)."}}
    (OUTPUT / "consolidated_pit_audit.json").write_text(json.dumps(audit, indent=2, default=str))
    write_manifest(OUTPUT / "consolidated_pit_manifest.json", [out_path], files + [OUTPUT / "prices_pit.parquet"],
                   {"script": "pit.consolidated"})
    print(json.dumps({k2: v for k2, v in audit.items() if k2 != "P2_retest"}, default=str))
    print(json.dumps({k2: v for k2, v in audit["P2_retest"].items() if k2 != "worst"}))
    for w in audit["P2_retest"]["worst"]:
        print("  worst", w)


if __name__ == "__main__":
    main()
