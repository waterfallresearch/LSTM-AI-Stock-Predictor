"""Extract independent, accession-bound SEC statement evidence for an audit."""
from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZipFile

import pandas as pd

from TrainingData.pit.fundamentals_gate import CALENDAR, END
from TrainingData.pit.fundamentals_pipeline import digest

TAGS = {
    "Assets", "StockholdersEquity", "NetIncomeLoss", "PreferredStockSharesOutstanding",
    "PreferredStockSharesIssued", "PreferredStockValue", "PreferredStockCarryingValue",
    "PreferredStockRedemptionAmount", "PreferredStockLiquidationPreferenceValue",
}


def statement_evidence(archive, accessions):
    """Keep SEC submission metadata and whole-entity, standard-taxonomy facts."""
    with ZipFile(archive) as source:
        submissions = pd.read_csv(source.open("sub.txt"), sep="\t", dtype=str, usecols=[
            "adsh", "cik", "form", "period", "fy", "fp", "accepted",
        ])
        submissions = submissions.loc[submissions.adsh.isin(accessions)].copy()
        submissions["accepted_et"] = pd.to_datetime(submissions.accepted).dt.tz_localize(
            "America/New_York", ambiguous="raise", nonexistent="raise"
        )
        submissions["period"] = pd.to_datetime(submissions.period, format="%Y%m%d")
        valid = submissions.accepted_et.le(CALENDAR.session_close(END)) & submissions.period.le(END)
        submissions = submissions.loc[valid].drop(columns="accepted")
        keys = set(submissions.adsh)
        frames = []
        cols = ["adsh", "tag", "version", "ddate", "qtrs", "uom", "segments", "coreg", "value"]
        for part in pd.read_csv(source.open("num.txt"), sep="\t", dtype=str, usecols=cols, chunksize=250_000):
            selected = part.adsh.isin(keys) & part.tag.isin(TAGS) & part.version.str.startswith(
                "us-gaap/", na=False
            ) & part.segments.isna() & part.coreg.isna()
            frames.append(part.loc[selected, cols].drop(columns=["segments", "coreg"]))
        numbers = pd.concat(frames, ignore_index=True).drop_duplicates()
        numbers["ddate"] = pd.to_datetime(numbers.ddate, format="%Y%m%d")
        numbers = numbers.loc[numbers.ddate.le(END)].copy()
        labels = pd.read_csv(source.open("pre.txt"), sep="\t", dtype=str,
                             usecols=["adsh", "tag", "version", "stmt", "plabel"])
        labels = labels.loc[labels.adsh.isin(keys) & labels.tag.isin(TAGS)]
    return submissions, numbers, labels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("accessions", type=Path, help="Parquet with an accession column")
    parser.add_argument("output", type=Path)
    parser.add_argument("archives", type=Path, nargs="+")
    args = parser.parse_args()
    accessions = set(pd.read_parquet(args.accessions, columns=["accession"]).accession.dropna())
    args.output.mkdir(parents=True, exist_ok=False)
    for path in args.archives:
        submissions, numbers, labels = statement_evidence(path, accessions)
        for name, frame in (("submissions", submissions), ("numbers", numbers), ("labels", labels)):
            frame.to_parquet(args.output / f"{path.stem}_{name}.parquet", index=False)
        print(path.name, digest(path), len(submissions), len(numbers), len(labels))


if __name__ == "__main__":
    main()
