import pandas as pd

from TrainingData.pit.edgar_coverage import summarize


def test_filing_match_preserves_denominator_and_respects_prior_session():
    signal = pd.Timestamp("2024-11-29")
    prior = pd.Timestamp("2024-11-27")
    roster = pd.DataFrame({"signal": [signal] * 4, "prior_session": [prior] * 4,
                           "permno": [1, 2, 3, 4]})
    links = pd.DataFrame([
        (signal, 1, "A", "01"), (signal, 2, "B", "02"),
        (signal, 3, "A", "01"), (signal, 3, "B", "02"),
    ], columns=["signal", "permno", "gvkey", "cik"])
    filings = pd.DataFrame([
        ("01", "a", "10-Q", "2024-09-30", "2024-11-27T14:29:59Z"),
        ("02", "b", "10-Q", "2024-09-30", "2024-11-27T14:30:00Z"),
    ], columns=["cik", "accessionNumber", "form", "reportDate", "acceptanceDateTime"])
    periods = pd.DataFrame([
        ("A", "2024-09-30", "2024-11-26"), ("B", "2024-09-30", "2024-11-26"),
    ], columns=["gvkey", "datadate", "vintage"])
    result = summarize(roster, links, filings, periods)
    assert result.link_count.tolist() == [1, 1, 2, 0]
    assert result.filing_period_match.tolist() == [True, False, False, False]
