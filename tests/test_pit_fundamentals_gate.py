import pandas as pd
import pytest

from TrainingData.pit.fundamentals_gate import (
    candidate_links, filing_session, freeze_roster, sec_submissions,
)


def test_filing_session_exact_open_and_after_hours():
    assert filing_session("2024-07-02T17:31:00-04:00", "2024-07-02") == pd.Timestamp("2024-07-03")
    assert filing_session("2024-07-03T09:30:00-04:00", "2024-07-02") == pd.Timestamp("2024-07-05")
    assert filing_session("2024-07-03T12:59:59-04:00", "2024-07-02") == pd.Timestamp("2024-07-05")


def test_filing_session_cutoff_and_dates():
    assert filing_session("2024-12-31T16:00:01-05:00", "2024-12-30") is None
    assert filing_session("2024-12-27T10:00:00-05:00", "2024-12-31") is None
    with pytest.raises(ValueError):
        filing_session("2024-12-30", "2024-12-30")
    assert filing_session("2022-07-26T20:32:11Z", "2022-07-25") == pd.Timestamp("2022-07-27")


def test_month_end_roster_preserves_removed_names():
    inputs = pd.DataFrame({
        "permno": [1, 2],
        "mbrstartdt": ["2010-01-01", "2024-11-29"],
        "mbrenddt": [None, "2024-12-30"],
    })
    roster = freeze_roster(inputs)
    assert roster.signal.nunique() == 108
    assert roster.loc[roster.permno.eq(2), "signal"].tolist() == [pd.Timestamp("2024-11-29")]
    assert roster.iloc[-1].prior_session == pd.Timestamp("2024-12-30")
    with pytest.raises(ValueError, match="ambiguous"):
        freeze_roster(pd.concat([inputs, inputs.iloc[:1]]))


def test_sec_ingestion_keeps_periodic_pre_cutoff_accession_only():
    rows = sec_submissions({
        "accessionNumber": ["0001418091-22-000143", "0001418091-22-000147", "0001418091-25-000001"],
        "form": ["8-K", "10-Q", "10-K/A"],
        "reportDate": ["2022-07-22", "2022-06-30", "2022-06-30"],
        "acceptanceDateTime": ["2022-07-22T12:00:46Z", "2022-07-26T20:32:11Z", "2025-01-02T13:00:00Z"],
    }, "0001418091")
    assert rows.accessionNumber.tolist() == ["0001418091-22-000147"]


def test_dated_candidates_keep_missing_and_ambiguous_rows():
    date = pd.Timestamp("2022-06-30")
    roster = pd.DataFrame({"signal": [date] * 3, "permno": [1, 2, 3]})
    links = pd.DataFrame([
        (1, "A", "001", "2020-01-01", "2024-12-31"),
        (1, "B", "002", "2022-07-01", "2024-12-31"),
        (2, "B", "002", "2020-01-01", "2024-12-31"),
        (2, "C", "003", "2020-01-01", "2024-12-31"),
    ], columns=["permno", "gvkey", "cik", "linkdt", "linkenddt"])
    assert candidate_links(roster, links).cik_candidates.tolist() == [1, 2, 0]
