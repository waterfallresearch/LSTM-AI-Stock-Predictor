import pandas as pd
import pytest

from TrainingData.pit.earnings_gate import (
    build_panel,
    consensus_cutoffs,
    consensus_pair,
    event_session,
    measure_coverage,
    snapshot_session,
)


def test_release_after_shortened_session_and_date_only_snapshot():
    cutoff, _ = consensus_cutoffs(pd.Timestamp("2024-11-29 14:00", tz="America/New_York"))
    assert cutoff.date().isoformat() == "2024-11-27"
    usable = snapshot_session(pd.Timestamp("2024-11-29"), date_only=True)
    assert usable.date().isoformat() == "2024-12-02"


def test_cutoff_seal_and_strictly_later_open():
    with pytest.raises(ValueError, match="knowledge cutoff"):
        consensus_cutoffs(pd.Timestamp("2024-12-31 16:01", tz="America/New_York"))
    usable = snapshot_session(pd.Timestamp("2024-12-31 09:30", tz="America/New_York"), date_only=False)
    assert usable.date().isoformat() == "2025-01-02"


def test_event_session_requires_both_public_and_vendor_evidence():
    public = pd.Timestamp("2024-10-31 16:31", tz="America/New_York")
    assert event_session(public, pd.Timestamp("2024-11-01"), vendor_date_only=True) == pd.Timestamp(
        "2024-11-04"
    )
    with pytest.raises(ValueError, match="timezone"):
        event_session(public, pd.Timestamp("2024-11-01 09:15"), vendor_date_only=False)
    with pytest.raises(ValueError, match="development window"):
        event_session(public, pd.Timestamp("2024-12-31"), vendor_date_only=True)


def test_pair_ignores_unavailable_candidates_and_quarantines_conflicts():
    public = pd.Timestamp("2024-10-31 16:31", tz="America/New_York")
    recent, old = consensus_cutoffs(public)
    rows = pd.DataFrame({
        "observation_session": pd.to_datetime(["2024-10-29", "2024-10-30", old, old]),
        "usable_session": pd.to_datetime([recent, "2024-10-31", old, old]),
        "mean_eps": [1.5, 99.0, 1.25, 1.0],
    })
    assert consensus_pair(rows, public) == (1.5, None)
    assert consensus_pair(rows.iloc[:3], public) == (1.5, 1.25)


def test_panel_preserves_denominator_and_supersedes_only_after_availability():
    roster = pd.DataFrame({
        "permno": [1, 2, 1],
        "signal": pd.to_datetime(["2024-10-31", "2024-10-31", "2024-11-29"]),
        "prior_session": pd.to_datetime(["2024-10-30", "2024-10-30", "2024-11-27"]),
    })
    events = pd.DataFrame({
        "permno": [1, 1],
        "period_end": pd.to_datetime(["2024-06-30", "2024-09-30"]),
        "release_day": pd.to_datetime(["2024-08-01", "2024-10-30"]),
        "usable_session": pd.to_datetime(["2024-08-02", "2024-10-31"]),
        "link_start": pd.Timestamp("2016-01-01"),
        "link_end": pd.Timestamp("2024-12-31"),
        "verified": [True, False],
        "actual_eps": [1.25, 1.5],
        "recent_consensus": [1, 1],
        "older_consensus": [0.75, 0.75],
    })
    panel = build_panel(roster, events)
    assert len(panel) == len(roster)
    assert panel.earnings_status.to_list() == ["complete", "no_eligible_event", "unverified_event"]
    assert panel.surprise.iloc[0] == panel.revision.iloc[0] == 0.25
    assert panel.surprise.iloc[1:].isna().all()


def test_coverage_retains_unknown_size_and_censored_delisting_rows():
    panel = pd.DataFrame({
        "signal": pd.to_datetime(["2023-11-30", "2023-11-30", "2024-11-29"]),
        "delist_date": pd.to_datetime(["2024-06-01", None, None]),
        "size_tercile": [1, None, 1],
        "surprise": [0.5, 0.5, None],
        "revision": [0.25, None, None],
        "earnings_status": ["complete", "incomplete_consensus", "no_eligible_event"],
    })
    result = measure_coverage(panel)
    assert result["overall"] == {"rows": 3, "complete": 1, "rate": 1 / 3}
    assert result["size_tercile_lower_bound"][1]["rate"] == 1 / 3
    assert result["delisting"] == {"rows": 1, "complete": 1, "rate": 1}
    assert result["delisting_censored"] == result["unknown_size"] == 1
