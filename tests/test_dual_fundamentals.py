import pandas as pd

from TrainingData.pit.dual_fundamentals import DEVELOPMENT_END, PILOT, select_revenue, snapshot_end


def test_repligen_backfilled_value_requires_amended_filing():
    quarter = PILOT[1]
    wrds = [
        (pd.Timestamp("2024-07-30"), pd.Timestamp("2024-11-11"), 154_073_000),
        (pd.Timestamp("2024-11-12"), pd.Timestamp("2024-11-27"), 160_675_000),
        (pd.Timestamp("2024-11-28"), DEVELOPMENT_END, 158_839_000),
    ]
    lseg = {158_839_000}
    expected = {
        "2024-07-30": (None, "awaiting_filing"),
        "2024-07-31": (154_073_000, "wrds_snapshot"),
        "2024-09-19": (None, "filing_withdrawn"),
        "2024-11-18": (None, "filing_withdrawn"),
        "2024-11-19": (158_839_000, "lseg_sec_anchored"),
        "2024-11-29": (158_839_000, "wrds_snapshot"),
    }
    for session, result in expected.items():
        assert select_revenue(
            quarter.filings, pd.Timestamp(session), wrds, lseg, allow_sec_reconstruction=True,
        )[:2] == result
    assert select_revenue(
        quarter.filings, pd.Timestamp("2024-07-31"), wrds, lseg,
        prefer="lseg", allow_sec_reconstruction=True,
    )[:2] == (
        154_073_000, "wrds_snapshot",
    )
    assert select_revenue(quarter.filings, pd.Timestamp("2024-11-19"), wrds, lseg)[:2] == (
        None, "no_verified_vendor_value",
    )


def test_unverified_candidates_remain_missing():
    quarter = PILOT[0]
    assert select_revenue(quarter.filings, pd.Timestamp("2024-02-02"), [], {1})[:2] == (
        None, "no_verified_vendor_value",
    )


def test_open_ended_snapshot_dates_are_bounded():
    assert snapshot_end("9999-12-31") == DEVELOPMENT_END
    assert snapshot_end(float("nan")) == DEVELOPMENT_END
