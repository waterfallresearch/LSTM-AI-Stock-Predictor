"""Acquire isolated LSEG earnings pilot data for subsequent vintage validation."""
from __future__ import annotations

import argparse
from datetime import date
from hashlib import file_digest
import json
import logging
from pathlib import Path

from TrainingData.pit.lseg_deals import open_session


FIELDS = {
    "daily_consensus": (
        ["TR.EPSMean.calcdate", "TR.EPSMean.periodenddate", "TR.EPSMean", "TR.EPSNumberOfEstimates"],
        {"Frq": "D", "Period": "FQ1"},
    ),
    "quarterly_actual": (
        ["TR.EPSActValue.date", "TR.EPSActValue.periodenddate", "TR.EPSActValue", "TR.EPSActReportDate"],
        {"Frq": "FQ", "Period": "FQ0"},
    ),
}
END = date(2024, 12, 31)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--rics", nargs="+", required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    if not args.start <= args.end <= END:
        parser.error("Specify ordered acquisition dates through 2024-12-31")

    import lseg.data as ld

    logging.disable(logging.CRITICAL)
    session = open_session(ld)
    records = {}
    try:
        args.output.mkdir(parents=True, exist_ok=False)
        for name, (fields, schedule) in FIELDS.items():
            parameters = dict(schedule, SDate=args.start.isoformat(), EDate=args.end.isoformat(), Curn="USD")
            try:
                frame = ld.get_data(universe=args.rics, fields=fields, parameters=parameters)
            except Exception as exc:
                records[name] = {"status": type(exc).__name__, "parameters": parameters, "fields": fields}
                continue
            filename = args.output / f"{name}.csv"
            frame.to_csv(filename, index=False)
            with filename.open("rb") as handle:
                sha256 = file_digest(handle, "sha256").hexdigest()
            records[name] = {
                "status": "retrieved", "rows": len(frame), "nonnull": frame.notna().sum().to_dict(),
                "parameters": parameters, "fields": fields, "sha256": sha256,
            }
    finally:
        session.close()
    (args.output / "manifest.json").write_text(
        json.dumps({"rics": args.rics, "datasets": records}, indent=2), encoding="utf-8"
    )
    if any(record["status"] != "retrieved" or not record["rows"] for record in records.values()):
        raise SystemExit("One or more requested datasets were unavailable. See the manifest.")


if __name__ == "__main__":
    main()
