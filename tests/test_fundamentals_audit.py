from decimal import Decimal

import pandas as pd

from TrainingData.pit.fundamentals_audit import audit_frame, independent_cap


def test_independent_cap_requires_the_full_class_set_and_crsp_units():
    prices = pd.DataFrame({"permno": [1, 2], "price": ["94.09", "10.25"],
                           "shrout": ["5544583", "5"]})
    assert independent_cap([1, 2], prices) == Decimal("521689865720.00")
    assert independent_cap([1, 3], prices) is None


def test_accession_audit_has_disjoint_acceptance_and_rejection():
    signal = pd.Timestamp("2024-09-30")
    ready = pd.DataFrame([{
        "gvkey": "001", "cik": "01", "signal": signal, "prior_session": pd.Timestamp("2024-09-27"),
        "permno": 7, "permco": 9, "start": "2020-01-01", "stop": "2024-12-31",
        "size_tercile": 2, "delist_date": pd.NaT, "cap": 1000.0,
    }])
    inputs = pd.DataFrame([
        ("001", "01", "original", "10-Q", pd.Timestamp("2024-06-30"), pd.Timestamp("2024-08-01"), 2, 1, 1),
        ("001", "01", "original", "10-Q", pd.Timestamp("2024-06-30"), pd.Timestamp("2024-08-02"), 2, 1, 1),
    ], columns=["gvkey", "cik", "accession", "form", "period", "usable", "assets", "net_income", "book_equity"])
    rejected = pd.DataFrame([("001", "01", "original", "temporary_missing"),
                             ("001", "01", "bad", "no_match")],
                            columns=["gvkey", "cik", "accession", "reason"])
    frame = audit_frame(inputs, ready, rejected)
    assert frame.accession.tolist() == ["original", "bad"]
    assert frame.disposition.tolist() == ["accepted", "rejected"]
