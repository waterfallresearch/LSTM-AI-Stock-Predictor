"""Extract independent, accession-bound SEC statement evidence for an audit."""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
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


def observed_fact(document, tag, period, *, duration=None, unit="USD"):
    """Select an unambiguous independent XBRL fact with stated rounding."""
    facts = set()
    for fact in document.get("facts", []):
        if fact["tag"] != tag or fact["end"] != period or not fact["ns"].startswith("http://fasb.org/us-gaap/"):
            continue
        if str(fact.get("unit", "")).split(":")[-1] != unit:
            continue
        start = fact.get("start")
        if duration is None and start is not None:
            continue
        if duration is not None and (not start or not duration[0] <= (
            pd.Timestamp(period) - pd.Timestamp(start)
        ).days <= duration[1]):
            continue
        try:
            amount = Decimal(fact["value"])
            decimals = fact.get("decimals")
            rounding = Decimal(0) if decimals == "INF" else Decimal("0.5").scaleb(-int(decimals))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if amount.is_finite():
            facts.add((amount, rounding, start))
    # Some filings repeat the same fact at different display precision.
    values = {(value, start) for value, _, start in facts}
    if len(values) != 1:
        return None
    value, start = next(iter(values))
    return value, min(tolerance for _, tolerance, _ in facts), start


def check_vintage_numbers(vintage, instances):
    """Independently reconcile accepted assets, quarterly income and book equity."""
    accession = vintage.accession
    document = instances.get(accession, {})
    period = vintage.period.date().isoformat()
    failures = []
    if not document.get("instance_sha256"):
        return ["missing_original_xbrl_instance"]

    def equals(fact, observed):
        return fact is not None and abs(fact[0] - Decimal(str(observed))) <= fact[1]

    for tag, wanted in (("Assets", vintage.assets),):
        if not equals(observed_fact(document, tag, period), wanted):
            failures.append("assets")
    stockholder = observed_fact(document, "StockholdersEquity", period)
    preferred = observed_fact(document, "PreferredStockCarryingValue", period)
    if preferred is None:
        shares = observed_fact(document, "PreferredStockSharesOutstanding", period, unit="shares")
        issued = observed_fact(document, "PreferredStockSharesIssued", period, unit="shares")
        reported = observed_fact(document, "PreferredStockValue", period)
        redemption = [observed_fact(document, tag, period) for tag in (
            "PreferredStockRedemptionValue", "PreferredStockRedemptionAmount",
            "PreferredStockLiquidationPreferenceValue",
        )]
        if shares and shares[0] == 0 and (issued is None or issued[0] == 0) and (
            reported is None or reported[0] == 0
        ) and all(value is None or value[0] == 0 for value in redemption):
            preferred = (Decimal(0), Decimal(0), None)
    equity = (stockholder[0] - preferred[0], stockholder[1] + preferred[1], None) if stockholder and preferred else None
    if not equals(equity, vintage.book_equity):
        failures.append("parent_common_equity")
    lineage = tuple(vintage.net_income_accessions)
    if len(lineage) == 2 and lineage[0] == accession:
        annual = observed_fact(document, "NetIncomeLoss", period, duration=(350, 380))
        interim_doc = instances.get(lineage[1], {})
        interim_period = interim_doc.get("report_period")
        interim = observed_fact(interim_doc, "NetIncomeLoss", interim_period,
                                duration=(255, 285)) if interim_period else None
        income = (annual[0] - interim[0], annual[1] + interim[1], annual[2]) if (
            annual and interim and annual[2] == interim[2]
        ) else None
    else:
        income = observed_fact(document, "NetIncomeLoss", period, duration=(80, 100)) if (
            lineage == (accession,)
        ) else None
    if not equals(income, vintage.net_income):
        failures.append("quarterly_net_income")
    return failures


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
