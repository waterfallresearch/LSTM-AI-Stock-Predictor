import pandas as pd

from TrainingData.pit.fundamentals_receipts import accession_receipts


def test_receipts_use_exact_period_and_do_not_infer_preferred_absence():
    submissions = pd.DataFrame([
        ("0000000123", "a", "10-Q", "2024-09-30", "2024-11-05T21:00:00Z"),
        ("0000000123", "b", "10-Q", "2024-06-29", "2024-07-02T20:00:00Z"),
    ], columns=["cik", "accessionNumber", "form", "reportDate", "acceptanceDateTime"])
    facts = {
        "Assets": [{"accn": "a", "end": "2024-09-30", "val": 100}],
        "StockholdersEquity": [{"accn": "a", "end": "2024-09-30", "val": 60}],
        "NetIncomeLoss": [
            {"accn": "a", "start": "2024-07-01", "end": "2024-09-30", "val": 2},
            {"accn": "a", "start": "2024-01-01", "end": "2024-09-30", "val": 6},
        ],
    }
    spans = pd.DataFrame({"gvkey": ["000001"], "start": [pd.Timestamp("2020-01-01")],
                          "stop": [pd.Timestamp("2024-12-31")]})
    labels = {("000001", pd.Timestamp("2024-09-30")): (2024, 3, 12),
              ("000001", pd.Timestamp("2024-06-30")): (2024, 2, 12)}
    accepted, rejected = accession_receipts(submissions, facts, spans, labels, "source-hash")
    assert [(r["income_type"], r["income"]) for r in accepted] == [("quarter", 2), ("nine_months", 6)]
    assert all(not r["preferred_verified"] for r in accepted)
    assert len(rejected) == 1
    assert rejected[0]["reason"] == "missing_or_conflicting_exact_fiscal_labels"
