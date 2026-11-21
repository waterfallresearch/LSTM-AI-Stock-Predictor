"""Read-only probe of LSEG intraday history coverage (research/latency_2026-11-20_preregistration.md, gate G2).

For a few RICs and start dates, request a short window of 5-minute and 1-minute bars and record what comes back:
rows, first/last timestamps, time zone, columns, and whether a 15:35-15:40 New York bar exists. It also lists the
daily-history field names, so a closing-auction price field can be identified from what the entitlement returns
rather than guessed.

Every request window ends before 2025-01-02 (the reserved confirmation period is never read).
Output: TrainingData/indicators_data/lseg/intraday_probe/<UTC stamp>/manifest.json (gitignored).
Requires a signed-in LSEG Workspace and LSEG_APP_KEY (same as lseg_download.py).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

CONFIRM_START = pd.Timestamp("2025-01-02")
RICS = ["AAPL.O", "MSFT.O", "JPM.N", "XOM.N", "A.N", "AA.N", "AAL.OQ", "AAP.N", "BSX.N", "AABA.OQ^J19"]
STARTS = ["2016-03-01", "2019-03-01", "2021-03-01", "2023-03-01", "2024-12-02"]
INTERVALS = ["5min", "1min"]
WINDOW_DAYS = 7
OUT = Path(__file__).resolve().parent / "indicators_data" / "lseg" / "intraday_probe"


def open_session():
    import lseg.data as ld
    logging.disable(logging.CRITICAL)  # SDK diagnostics can contain authentication context.
    keys = []
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as registry:
                keys.append(winreg.QueryValueEx(registry, "LSEG_APP_KEY")[0])
        except OSError:
            pass
    keys.append(os.environ.get("LSEG_APP_KEY"))
    keys = list(dict.fromkeys(k.strip() for k in keys if k and k.strip()))
    if not keys:
        raise SystemExit("LSEG_APP_KEY is not configured.")
    for key in keys:
        s = ld.session.desktop.Definition(app_key=key).get_session()
        if s.open().name == "Opened":
            ld.session.set_default(s)
            return ld, s
        s.close()
    raise SystemExit("Workspace authentication failed; check your app key and login.")


def summarize_bars(frame: pd.DataFrame | None) -> dict:
    if frame is None or frame.empty:
        return {"status": "empty", "rows": 0}
    idx = pd.DatetimeIndex(frame.index)
    tz = str(idx.tz) if idx.tz is not None else "naive"
    ny = idx.tz_convert("America/New_York") if idx.tz is not None else idx
    late = [(t.hour, t.minute) for t in ny if (t.hour, t.minute) >= (15, 30) and (t.hour, t.minute) <= (16, 5)]
    return {"status": "ok", "rows": int(len(frame)), "first": str(idx.min()), "last": str(idx.max()), "tz": tz,
            "columns": [str(c) for c in frame.columns],
            "sessions": int(len(set(ny.date))),
            "late_bar_times_ny_if_tz_utc": sorted({f"{h:02d}:{m:02d}" for h, m in late}),
            "has_1535_or_1540_bar": any(x in {(15, 35), (15, 40)} for x in late)}


RESERVED_STARTS = ["2025-01-06", "2025-06-02", "2025-11-17", "2026-05-04", "2026-11-09"]


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--reserved-coverage", action="store_true",
                    help="Probe windows inside the reserved period (user-approved 2026-11-20). Only coverage "
                         "metadata is stored: counts, timestamps, columns. No prices or returns are kept.")
    args = ap.parse_args()
    starts = RESERVED_STARTS if args.reserved_coverage else STARTS
    end_cap = pd.Timestamp.today().normalize() if args.reserved_coverage else CONFIRM_START - pd.Timedelta(days=1)
    ld, session = open_session()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    dest = OUT / stamp
    dest.mkdir(parents=True, exist_ok=False)
    manifest = {"retrieved_at_utc": stamp, "sdk_version": ld.__version__, "rics": RICS, "starts": starts,
                "reserved_coverage": args.reserved_coverage, "stores_prices": False,
                "intervals": INTERVALS, "window_days": WINDOW_DAYS, "requests": [], "daily_fields": {}}
    try:
        for ric in RICS:
            for interval in INTERVALS:
                for start in starts:
                    s = pd.Timestamp(start)
                    e = min(s + pd.Timedelta(days=WINDOW_DAYS), end_cap)
                    rec = {"ric": ric, "interval": interval, "start": str(s.date()), "end": str(e.date())}
                    try:
                        frame = ld.get_history(universe=ric, interval=interval, start=str(s.date()), end=str(e.date()))
                        rec.update(summarize_bars(frame))
                    except Exception as exc:  # entitlement / retention errors are the result we want to record
                        rec.update(status="error", error=f"{type(exc).__name__}: {str(exc)[:300]}")
                    manifest["requests"].append(rec)
                    print(ric, interval, start, rec.get("status"), rec.get("rows"), rec.get("first", rec.get("error", "")))
            # daily field discovery: which columns does the entitlement return with no field list?
            try:
                d = ld.get_history(universe=ric, interval="1D", start="2024-11-01", end="2024-11-29")
                manifest["daily_fields"][ric] = [str(c) for c in d.columns] if d is not None else []
            except Exception as exc:
                manifest["daily_fields"][ric] = f"error: {type(exc).__name__}: {str(exc)[:200]}"
    finally:
        session.close()
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2))

    # earliest window that returned bars, per RIC and interval
    ok = pd.DataFrame([r for r in manifest["requests"] if r.get("status") == "ok"])
    if not ok.empty:
        earliest = ok.groupby(["ric", "interval"])["start"].min().unstack()
        print("\nEarliest start window with data:\n", earliest.to_string())
    print(f"\nWrote {dest / 'manifest.json'}")


if __name__ == "__main__":
    main()
