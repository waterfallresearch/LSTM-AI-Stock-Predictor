"""Build month-end features from independently reconciled filing and vendor inputs."""
from __future__ import annotations

import numpy as np
import pandas as pd

from TrainingData.pit.fundamentals_gate import CALENDAR, END

FEATURES = ["profitability", "asset_growth", "book_to_market"]
SECURITY_KEY = ["signal", "permno"]


def reconcile_facts(facts: list[dict], accession: str, report_end: str, start: str | None = None):
    """Accept an unambiguous USD value from the specific accession and period."""
    numbers = {
        row["val"] for row in facts
        if row["accn"] == accession and row["end"] == report_end and row.get("start") == start
    }
    return next(iter(numbers)) if len(numbers) == 1 else None


def fourth_quarter(annual: dict, nine_months: dict):
    """Subtract compatible year-to-date values and preserve both source records."""
    dimensions = ("gvkey", "cik", "fiscal_year", "currency", "basis", "start")
    if any(annual[key] != nine_months[key] for key in dimensions):
        return None
    duration = (pd.Timestamp(annual["period"]) - pd.Timestamp(nine_months["period"])).days
    if not 80 <= duration <= 100:
        return None
    return {
        "value": annual["value"] - nine_months["value"],
        "usable": max(annual["usable"], nine_months["usable"]),
        "inputs": (annual["accession"], nine_months["accession"]),
    }


def aggregate_market_cap(classes: pd.DataFrame, expected: pd.DataFrame) -> pd.DataFrame:
    """Require a complete expected common-class roster with valid unadjusted inputs."""
    keys = ["session", "permco"]
    class_key = keys + ["permno"]
    if classes.duplicated(class_key).any() or expected.duplicated(class_key).any():
        raise ValueError("Duplicate issuer share-class record")
    joined = expected[class_key].merge(classes, on=class_key, how="outer", indicator=True)
    price = pd.to_numeric(joined.price, errors="coerce")
    shares = pd.to_numeric(joined.shares, errors="coerce")
    valid = np.isfinite(price) & price.gt(0) & np.isfinite(shares) & shares.gt(0)
    data = joined.assign(value=(price * shares).where(valid & joined._merge.eq("both")))
    grouped = data.groupby(keys)
    result = grouped.value.agg(cap="sum", valid="count")
    result["cap"] = result.cap.where(result.valid.eq(grouped.size()))
    return result[["cap"]].reset_index()


def _latest_known(group: pd.DataFrame, prior: pd.Timestamp) -> pd.DataFrame:
    usable = group.loc[group.usable.le(prior) & group.period.le(prior)]
    if usable.empty:
        return usable
    # A verified amendment replaces the original only after its effective session.
    by_period = ["fiscal_year", "fiscal_quarter"]
    by_accession = by_period + ["accession"]
    # Daily WRDS slices of the same filing describe one filing, not competing originals.
    if "vendor_date" in usable.columns:
        usable = usable.sort_values(["usable", "vendor_date"]).drop_duplicates(by_accession, keep="last")
    originals = usable.loc[usable.form.isin(["10-Q", "10-K"])]
    unique_original = originals.loc[~originals.duplicated(by_period, keep=False)]
    baseline = unique_original[by_period + ["period", "accepted_at"]].rename(
        columns={"accepted_at": "original_at"}
    )
    eligible = usable.merge(baseline, on=by_period + ["period"])
    eligible = eligible.loc[
        (eligible.form.isin(["10-Q", "10-K"]) & eligible.accepted_at.eq(eligible.original_at))
        | (eligible.form.isin(["10-Q/A", "10-K/A"])
           & eligible.accepted_at.gt(eligible.original_at)
           & eligible[["assets", "net_income", "book_equity"]].notna().any(axis=1))
    ]
    # Preserve ambiguous quarters as missing placeholders so stale periods cannot replace them.
    rejected = usable.loc[~pd.MultiIndex.from_frame(usable[by_period]).isin(
        pd.MultiIndex.from_frame(eligible[by_period])
    )].drop_duplicates(by_period)
    rejected = rejected.assign(assets=np.nan, net_income=np.nan, book_equity=np.nan, accession=None)
    usable = pd.concat([eligible, rejected], ignore_index=True)
    ordered = usable.sort_values(by_period + ["accepted_at", "usable"])
    latest = ordered.drop_duplicates(by_period, keep="last")
    ties = ordered.merge(
        latest[by_period + ["accepted_at", "usable"]],
        on=by_period + ["accepted_at", "usable"],
    )
    ambiguous = ties.groupby(by_period).size()
    bad = ambiguous[ambiguous.gt(1)].index
    conflicting = pd.MultiIndex.from_frame(latest[by_period]).isin(bad)
    latest = latest.copy()
    latest.loc[conflicting, ["assets", "net_income", "book_equity"]] = np.nan
    latest.loc[conflicting, "accession"] = None
    return latest


def build_features(roster: pd.DataFrame, vintages: pd.DataFrame) -> pd.DataFrame:
    """Preserve the frozen denominator and store the participating vintage IDs."""
    if roster.duplicated(SECURITY_KEY).any():
        raise ValueError("Duplicate security-month")
    if roster.signal.gt(END).any() or vintages.accepted_at.gt(CALENDAR.session_close(END)).any():
        raise ValueError("Confirmation timestamp in feature inputs")
    if vintages.usable.gt(END).any():
        raise ValueError("Confirmation session in feature inputs")
    required = ["accepted_at", "usable", "period", "fiscal_year", "fiscal_quarter", "accession", "form"]
    if vintages[required].isna().any().any():
        raise ValueError("Incomplete filing lineage")
    prior = roster.signal.map({day: CALENDAR.previous_session(day) for day in roster.signal.unique()})
    if not prior.eq(roster.prior_session).all():
        raise ValueError("Prior session must immediately precede the signal")
    if (roster.cap.notna() & ~roster.cap_session.eq(roster.prior_session)).any():
        raise ValueError("Market cap must use the prior session")
    opens = {day: CALENDAR.session_open(day) for day in vintages.usable.unique()}
    if vintages.accepted_at.ge(vintages.usable.map(opens)).any():
        raise ValueError("Usable session precedes filing availability")
    duration = (vintages.period - vintages.net_income_start).dt.days
    if (vintages.net_income.notna() & ~duration.between(80, 100)).any():
        raise ValueError("Net income must cover one quarter")
    groups = {key: group for key, group in vintages.groupby(["gvkey", "cik"])}
    cache = {}
    values = []
    for row in roster.itertuples(index=False):
        key = (row.gvkey, row.cik)
        result = dict.fromkeys(FEATURES + [
            "accession", "year_ago_accession", "book_equity", "period_age_days", "net_income_accessions",
        ])
        result["status"] = "no_verified_filing"
        if key in groups and pd.notna(row.admitted_from) and row.admitted_from <= row.prior_session:
            cache_key = (*key, row.prior_session, row.start, row.stop)
            if cache_key not in cache:
                group = groups[key]
                in_window = group.period.between(pd.Timestamp(row.start), pd.Timestamp(row.stop))
                cache[cache_key] = _latest_known(group.loc[in_window], row.prior_session)
            history = cache[cache_key]
            if not history.empty:
                latest = history.sort_values("period").iloc[-1]
                age = (row.signal - latest.period).days
                result["period_age_days"] = age
                if age > 180 or pd.isna(latest.accession):
                    result["status"] = "stale_filing" if age > 180 else "ambiguous_vintage"
                    values.append(result)
                    continue
                previous = history.loc[
                    history.fiscal_year.eq(latest.fiscal_year - 1)
                    & history.fiscal_quarter.eq(latest.fiscal_quarter)
                    & history.basis.eq(latest.basis)
                    & history.currency.eq(latest.currency)
                    & history.fiscal_year_end.eq(latest.fiscal_year_end)
                    & (latest.period - history.period).dt.days.between(364, 366)
                ]
                result["accession"] = latest.accession
                result["book_equity"] = latest.book_equity
                result["net_income_accessions"] = latest.net_income_accessions
                result["status"] = "incomplete_inputs"
                if np.isfinite(latest.assets) and latest.assets > 0:
                    result["profitability"] = latest.net_income / latest.assets
                    if len(previous) == 1 and np.isfinite(previous.iloc[0].assets) and previous.iloc[0].assets > 0:
                        result["asset_growth"] = latest.assets / previous.iloc[0].assets - 1
                        result["year_ago_accession"] = previous.iloc[0].accession
                if np.isfinite(row.cap) and row.cap > 0:
                    result["book_to_market"] = latest.book_equity / row.cap
                if all(pd.notna(result[feature]) for feature in FEATURES):
                    result["status"] = "complete"
        values.append(result)
    panel = pd.concat([roster.reset_index(drop=True), pd.DataFrame(values)], axis=1)
    panel["negative_book_equity"] = panel.book_equity.lt(0)
    return panel


def coverage(panel: pd.DataFrame) -> dict:
    """Calculate coverage against the frozen denominator and explicit subgroups."""
    complete = panel[FEATURES].notna().all(axis=1)
    years = complete.groupby(panel.signal.dt.year).mean()
    sizes = complete.groupby(panel.size_tercile).mean().reindex([1, 2, 3])
    counts = complete.groupby(panel.size_tercile).agg(["sum", "count"]).reindex([1, 2, 3])
    unknown_size = int(panel.size_tercile.isna().sum())
    lower_sizes = counts["sum"] / (counts["count"] + unknown_size)
    observed = (panel.signal + pd.DateOffset(years=1)).le(END)
    delists = observed & panel.delist_date.gt(panel.signal) & (
        panel.delist_date.le(panel.signal + pd.DateOffset(years=1))
    )
    return {
        "rows": len(panel),
        "complete": int(complete.sum()),
        "overall": float(complete.mean()),
        "year": years.to_dict(),
        "size_tercile": sizes.to_dict(),
        "size_tercile_lower_bound": lower_sizes.to_dict(),
        "delisting": {"denominator": int(delists.sum()), "rate": float(complete[delists].mean())},
        "delisting_censored": int((~observed).sum()),
        "missing_size_tercile": unknown_size,
        "month": complete.groupby(panel.signal.dt.strftime("%Y-%m")).mean().to_dict(),
        "status": panel.status.value_counts().to_dict(),
    }


def freeze_audit_sample(metadata: pd.DataFrame) -> pd.DataFrame:
    """Select fixed review rows using identifiers and preclassified strata only."""
    columns = ["audit_id", "disposition", "stratum", "mandatory"]
    data = metadata[columns].sort_values("audit_id").reset_index(drop=True)
    if data.audit_id.duplicated().any():
        raise ValueError("Duplicate audit identifiers")
    rng = np.random.default_rng(20261121)
    samples = []
    for disposition, limit in (("accepted", 120), ("rejected", 40)):
        rows = data.loc[data.disposition.eq(disposition)]
        mandatory = rows.loc[rows.mandatory]
        if len(rows) < limit or len(mandatory) > limit:
            raise ValueError(f"Cannot freeze required {disposition} audit sample")
        buckets = [
            iter(rng.permutation(stratum.index))
            for _, stratum in rows.loc[~rows.mandatory].groupby("stratum", sort=True, dropna=False)
        ]
        selected = []
        while len(selected) < limit - len(mandatory):
            for bucket in buckets:
                index = next(bucket, None)
                if index is not None:
                    selected.append(index)
                if len(selected) == limit - len(mandatory):
                    break
        samples.append(pd.concat([mandatory, rows.loc[selected]]))
    return pd.concat(samples, ignore_index=True)


def assess_gate(metrics: dict, audit: pd.DataFrame, frozen_sample: pd.DataFrame) -> dict:
    """Require every frozen audit item and every preregistered coverage floor."""
    receipts = frozen_sample[["audit_id"]].merge(
        audit[["audit_id", "resolved", "cap_error"]], on="audit_id",
        how="left", validate="one_to_one",
    )
    # A quarantined input can be resolved without a market-cap denominator.
    cap_required = frozen_sample.disposition.eq("accepted").to_numpy()
    cap_pass = receipts.cap_error.abs().le(0.01) | ~cap_required
    verified = receipts.resolved.eq(True) & cap_pass
    if len(frozen_sample) != 160 or not verified.all():
        return {"decision": "blocked", "unresolved_audit_rows": int((~verified).sum())}
    sizes = {int(key): value for key, value in metrics["size_tercile_lower_bound"].items()}
    years = {int(key): value for key, value in metrics["year"].items()}
    floors = {
        "overall": metrics["overall"] >= 0.80,
        "every_year": set(years) == set(range(2016, 2025))
        and all(rate >= 0.70 for rate in years.values()),
        "every_size_tercile": set(sizes) == {1, 2, 3}
        and all(rate >= 0.60 for rate in sizes.values()),
        "delisting": metrics["delisting"]["denominator"] > 0
        and metrics["delisting"]["rate"] >= 0.60,
    }
    return {"decision": "pass" if all(floors.values()) else "fail", "floors": floors}
