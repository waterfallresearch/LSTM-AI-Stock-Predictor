"""Download 5-minute LSEG bars for every S&P 500 member of the intraday window (user-approved use of the
reserved period, 2026-11-20; see research/preclose_2026-11-20_preregistration.md).

LSEG keeps about one rolling year of intraday history, so the oldest sessions disappear daily: run this early.
Stores the raw bars exactly as returned (all fields, naive UTC timestamps) per security; no analysis here.

Usage (system Python, which has lseg-data):
    python TrainingData/lseg_intraday_download.py [--out DIR] [--interval 5min]
Re-running with the same --out resumes: securities already saved are skipped.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lseg_intraday_probe import open_session  # noqa: E402  (same app-key / desktop-session logic)

PIT = Path(__file__).resolve().parent / "indicators_data" / "pit"
BASE = Path(__file__).resolve().parent / "indicators_data" / "lseg" / "intraday"
WINDOW = ("2025-11-17", "2026-11-18")      # first returned bars are 2025-11-19 (rolling retention)
CHUNK_DAYS = 64           # about 5,000 bars per request; a truncated reply is split automatically
WORKERS = 4


def universe() -> pd.DataFrame:
    m = pd.read_csv(PIT / "membership_pit.csv")
    m = m[(m["session"] >= WINDOW[0]) & (m["session"] <= WINDOW[1])]
    isins = set(m["isin"])
    sm = pd.read_csv(PIT / "security_master.csv")
    sm = sm[(sm["role"] == "primary") & (sm["valid_to"] > WINDOW[0]) & sm["isin"].isin(isins)]
    return sm[["isin", "ric", "valid_from", "valid_to"]].sort_values("isin").reset_index(drop=True)


def chunks(start: str, end: str, days: int):
    s, e = pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=1)
    while s < e:
        n = min(s + pd.Timedelta(days=days), e)
        yield s, n
        s = n


def fetch(ld, ric: str, s: pd.Timestamp, e: pd.Timestamp, interval: str, log: list, depth: int = 0) -> list:
    """Fetch [s, e); split the window if the result looks truncated (starts well after s)."""
    for attempt in range(3):
        try:
            f = ld.get_history(universe=ric, interval=interval, start=str(s), end=str(e))
            break
        except Exception as exc:  # transient gateway errors: back off and retry
            if attempt == 2:
                log.append({"ric": ric, "start": str(s), "end": str(e), "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
                return []
            time.sleep(2 * (attempt + 1))
    if f is None or f.empty:
        return []
    first = pd.Timestamp(f.index.min())
    if depth < 4 and (e - s) > pd.Timedelta(days=2) and first > s + pd.Timedelta(days=4) and s > pd.Timestamp("2025-11-25"):
        mid = s + (e - s) / 2
        log.append({"ric": ric, "start": str(s), "end": str(e), "split": True, "rows": len(f)})
        return fetch(ld, ric, s, mid, interval, log, depth + 1) + fetch(ld, ric, mid, e, interval, log, depth + 1)
    return [f]


def repair(out: Path, interval: str) -> None:
    """Re-fetch the windows that errored (timeouts) and securities saved empty; merge into the parquet files.
    Appends a 'repair' section to manifest.json. Safe to re-run."""
    uni = pd.read_csv(out / "universe.csv")
    log = json.loads((out / "progress.json").read_text())
    errs = [x for x in log if "error" in x]
    empty = {x["ric"] for x in log if x.get("rows") == 0 and "start" not in x}
    ld, session = open_session()
    rlog: list = []
    fixed, still = 0, []
    try:
        targets = [(e["ric"], pd.Timestamp(e["start"]), pd.Timestamp(e["end"])) for e in errs]
        targets += [(ric, s, e) for ric in sorted(empty) for s, e in chunks(*WINDOW, CHUNK_DAYS)]
        by_ric: dict = {}
        for ric, s, e in targets:
            by_ric.setdefault(ric, []).append((s, e))
        for ric, wins in by_ric.items():
            isin = uni.loc[uni["ric"] == ric, "isin"].iloc[0]
            parts = []
            for s, e in wins:
                got = []
                for attempt in range(4):
                    got = fetch(ld, ric, s, e, interval, rlog)
                    if got or not (rlog and rlog[-1].get("ric") == ric and "error" in rlog[-1]):
                        break
                    time.sleep(10 * (attempt + 1))
                parts += got
            if not parts:
                still.append(ric)
                continue
            new = pd.concat(parts)
            new.columns = [str(c) for c in new.columns]
            new.insert(0, "ric", ric)
            new.index.name = "ts_utc"
            path = out / f"{isin}.parquet"
            df = pd.concat([pd.read_parquet(path), new]) if path.exists() else new
            df = df[~df.index.duplicated(keep="last")].sort_index()
            df.to_parquet(path)
            fixed += 1
            print(f"repaired {ric}: +{len(new)} rows", flush=True)
    finally:
        session.close()
    man = json.loads((out / "manifest.json").read_text())
    man["repair"] = {"securities_targeted": len(by_ric), "repaired": fixed, "still_missing": still,
                     "windows_targeted": len(targets), "errors_on_retry": [x for x in rlog if "error" in x],
                     "finished_utc": datetime.now(timezone.utc).isoformat()}
    (out / "manifest.json").write_text(json.dumps(man, indent=1))
    print(json.dumps({k: v if not isinstance(v, list) else len(v) for k, v in man["repair"].items()}))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path)
    ap.add_argument("--interval", default="5min")
    ap.add_argument("--repair", action="store_true", help="re-fetch errored windows and empty securities in --out")
    args = ap.parse_args()
    if args.repair:
        repair(args.out, args.interval)
        return
    out = args.out or BASE / f"{args.interval}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    out.mkdir(parents=True, exist_ok=True)
    uni = universe()
    uni.to_csv(out / "universe.csv", index=False)
    ld, session = open_session()
    old = out / "progress.json"
    log: list = json.loads(old.read_text()) if old.exists() else []
    done = {p.stem for p in out.glob("*.parquet")}
    t0 = time.time()

    def one(r) -> dict:
        parts = []
        for s, e in chunks(*WINDOW, CHUNK_DAYS):
            parts += fetch(ld, r.ric, s, e, args.interval, log)
        if not parts:
            return {"isin": r.isin, "ric": r.ric, "rows": 0}
        df = pd.concat(parts)
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df.columns = [str(c) for c in df.columns]
        df.index.name = "ts_utc"
        df.insert(0, "ric", r.ric)
        df.to_parquet(out / f"{r.isin}.parquet")
        return {"isin": r.isin, "ric": r.ric, "rows": len(df), "first": str(df.index.min()), "last": str(df.index.max())}

    from concurrent.futures import ThreadPoolExecutor, as_completed
    todo = [r for r in uni.itertuples(index=False) if r.isin not in done]
    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futs = [pool.submit(one, r) for r in todo]
            for k, fu in enumerate(as_completed(futs)):
                rec = fu.result()
                log.append(rec)
                if k % 25 == 0:
                    print(f"{k + 1}/{len(todo)} {rec['ric']} rows={rec['rows']} elapsed={time.time() - t0:.0f}s", flush=True)
                    (out / "progress.json").write_text(json.dumps(log, indent=1))
    finally:
        session.close()
        (out / "progress.json").write_text(json.dumps(log, indent=1))
    saved = [x for x in log if x.get("rows", 0) > 0 and "start" not in x]
    manifest = {"interval": args.interval, "window": WINDOW, "chunk_days": CHUNK_DAYS, "securities": len(uni),
                "saved": len(saved), "empty": [x["ric"] for x in log if x.get("rows") == 0 and "start" not in x],
                "errors": [x for x in log if "error" in x], "splits": sum(1 for x in log if x.get("split")),
                "timestamps": "naive UTC as returned by lseg.data get_history",
                "finished_utc": datetime.now(timezone.utc).isoformat()}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(json.dumps({k: (v if not isinstance(v, list) else len(v)) for k, v in manifest.items()}, indent=1))


if __name__ == "__main__":
    main()
