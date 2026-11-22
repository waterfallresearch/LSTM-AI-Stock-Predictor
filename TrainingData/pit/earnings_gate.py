"""Timing and vintage selection for the point-in-time earnings data gate."""
from __future__ import annotations

from datetime import date

from exchange_calendars import get_calendar
import numpy as np
import pandas as pd


CALENDAR = get_calendar("XNYS")
END = pd.Timestamp("2024-12-31")


def consensus_cutoffs(public_at: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return close sessions for the pre-release and 21-session baseline snapshots."""
    public_at = pd.Timestamp(public_at)
    if public_at.tzinfo is None:
        raise ValueError("Public release time must include a verified timezone")
    day = pd.Timestamp(public_at.tz_convert("America/New_York").date())
    if day > END or public_at > CALENDAR.session_close(END):
        raise ValueError("Release exceeds the development knowledge cutoff")
    session = CALENDAR.date_to_session(day, direction="previous")
    if session.date() == day.date():
        session = CALENDAR.previous_session(session)
    return session, CALENDAR.session_offset(session, -21)


def snapshot_session(value: date | pd.Timestamp, *, date_only: bool) -> pd.Timestamp:
    """Map explicit timestamps or date-only end-of-day records to their first usable open."""
    stamp = pd.Timestamp(value)
    if date_only:
        if stamp.tzinfo is not None or stamp != stamp.normalize():
            raise ValueError("Date-only evidence must be an unzoned calendar date")
        stamp = (stamp + pd.DateOffset(days=1)).tz_localize("America/New_York")
    elif stamp.tzinfo is None:
        raise ValueError("Timestamp evidence must include a verified timezone")
    day = pd.Timestamp(stamp.tz_convert("America/New_York").date())
    session = CALENDAR.date_to_session(day, direction="next")
    if CALENDAR.session_open(session) <= stamp:
        return CALENDAR.next_session(session)
    return session


def event_session(
    public_at: pd.Timestamp, vendor_at: date | pd.Timestamp, *, vendor_date_only: bool
) -> pd.Timestamp:
    """Use the later first-open bound from independent public and vendor evidence."""
    usable = max(snapshot_session(public_at, date_only=False),
                 snapshot_session(vendor_at, date_only=vendor_date_only))
    if usable > END:
        raise ValueError("Event is not usable within the development window")
    return usable


def consensus_pair(verified: pd.DataFrame, public_at: pd.Timestamp) -> tuple[float | None, float | None]:
    """Select values from one prevalidated issuer, fiscal period, EPS basis and source."""
    values = []
    for cutoff in consensus_cutoffs(public_at):
        first = CALENDAR.session_offset(cutoff, -5)
        eligible = verified.loc[
            verified.usable_session.le(cutoff) & verified.observation_session.between(first, cutoff)
        ]
        if eligible.empty:
            values.append(None)
            continue
        latest = eligible.loc[eligible.observation_session.eq(eligible.observation_session.max()), "mean_eps"]
        unique = latest.drop_duplicates()
        values.append(float(unique.iloc[0]) if len(unique) == 1 and unique.notna().all() else None)
    return values[0], values[1]


def build_panel(roster: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Join verified security-event versions as of the prior session.

    Each input event has a dated permanent-security link and a usable session
    derived from both the original release and authenticated vendor availability.
    Unverified events cannot provide feature values, but are retained as blockers
    so a more recent unverified quarter cannot silently revive an older one.
    """
    keys = ["signal", "permno"]
    if roster.duplicated(keys).any() or roster.signal.gt(END).any():
        raise ValueError("Expected unique development security-month keys")
    if events.usable_session.isna().any() or events.usable_session.gt(END).any():
        raise ValueError("Events must have a documented development usable session")
    if events[["period_end", "release_day", "link_start", "link_end"]].isna().any().any() or (
        events.period_end.gt(events.release_day) | events.release_day.gt(events.usable_session)
    ).any():
        raise ValueError("Event dates must establish fiscal, release and identity chronology")
    if not roster.signal.map({day: CALENDAR.previous_session(day) for day in roster.signal.unique()}).eq(
        roster.prior_session
    ).all():
        raise ValueError("Roster prior sessions do not match the exchange calendar")
    candidates = roster[keys + ["prior_session"]].merge(events, on="permno", how="inner")
    candidates = candidates.loc[
        candidates.usable_session.le(candidates.prior_session)
        & candidates.link_start.le(candidates.signal)
        & candidates.link_end.ge(candidates.signal)
        & (candidates.signal - candidates.release_day).dt.days.between(0, 120)
    ]
    # First select the latest quarter, then the latest eligible version.
    order = keys + ["period_end", "usable_session"]
    latest = candidates.sort_values(order).drop_duplicates(keys, keep="last")
    latest = candidates.merge(latest[order], on=order, how="inner", validate="many_to_one")
    latest["ambiguous"] = latest.duplicated(keys, keep=False)
    latest = latest.drop_duplicates(keys).copy()
    admissible = latest.verified.eq(True) & ~latest.ambiguous
    surprise = latest.actual_eps - latest.recent_consensus
    revision = latest.recent_consensus - latest.older_consensus
    latest["surprise"] = surprise.where(admissible & np.isfinite(surprise))
    latest["revision"] = revision.where(admissible & np.isfinite(revision))
    latest["earnings_status"] = "incomplete_consensus"
    latest.loc[~latest.verified.eq(True), "earnings_status"] = "unverified_event"
    latest.loc[latest.ambiguous, "earnings_status"] = "ambiguous_event"
    latest.loc[latest[["surprise", "revision"]].notna().all(axis=1), "earnings_status"] = "complete"
    columns = keys + ["surprise", "revision", "earnings_status"]
    result = roster.merge(latest[columns], on=keys, how="left", validate="one_to_one")
    result["earnings_status"] = result.earnings_status.fillna("no_eligible_event")
    return result


def measure_coverage(panel: pd.DataFrame) -> dict:
    """Count completed feature pairs across the frozen denominator and subgroups."""
    available = panel[["surprise", "revision"]].notna()
    complete = available.all(axis=1)

    def group_rate(mask: pd.Series, additional_missing: int = 0) -> dict:
        rows = int(mask.sum())
        successes = int((complete & mask).sum())
        denominator = rows + additional_missing
        return {
            "rows": rows, "complete": successes,
            "rate": successes / denominator if denominator else None,
        }

    missing_size = int(panel.size_tercile.isna().sum())
    window_end = panel.signal + pd.DateOffset(years=1)
    observed = window_end.le(END)
    delisted = observed & panel.delist_date.gt(panel.signal) & panel.delist_date.le(window_end)
    return {
        "overall": group_rate(pd.Series(True, index=panel.index)),
        "feature_counts": available.sum().to_dict(),
        "year": {year: group_rate(panel.signal.dt.year.eq(year)) for year in range(2016, 2025)},
        "month": {str(month): group_rate(panel.signal.dt.to_period("M").eq(month))
                  for month in sorted(panel.signal.dt.to_period("M").unique())},
        "size_tercile_lower_bound": {
            size: group_rate(panel.size_tercile.eq(size), missing_size) for size in (1, 2, 3)
        },
        "unknown_size": missing_size,
        "delisting": group_rate(delisted),
        "delisting_censored": int((~observed).sum()),
        "status": panel.earnings_status.value_counts().to_dict(),
    }
