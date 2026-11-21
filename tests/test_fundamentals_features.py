import pandas as pd
import pytest

from TrainingData.pit.fundamentals_features import (
    aggregate_market_cap, assess_gate, build_features, coverage, fourth_quarter,
    freeze_audit_sample, reconcile_facts,
)
from TrainingData.pit.fundamentals_anchors import admit_links, reconcile_assets


def test_exact_accession_and_duration():
    facts = [{"accn": acc, "end": "2024-06-30", "start": start, "val": value}
             for acc, start, value in [("original", "2024-04-01", 3),
                                       ("amendment", "2024-04-01", 5),
                                       ("amendment", "2024-01-01", 8)]]
    assert reconcile_facts(facts, "amendment", "2024-06-30", "2024-04-01") == 5
    assert reconcile_facts(facts + [dict(facts[1], val=6)], "amendment",
                           "2024-06-30", "2024-04-01") is None


def test_original_asset_anchors_exclude_amendments_and_conflicts():
    filings = pd.DataFrame([
        ("01", "first", "10-Q", "2024-06-30", "2024-07-30T21:04:52Z"),
        ("01", "later", "10-Q/A", "2024-06-30", "2024-11-18T17:08:36Z"),
    ], columns=["cik", "accessionNumber", "form", "reportDate", "acceptanceDateTime"])
    facts = pd.DataFrame([
        ("01", "first", "2024-06-30", None, 200_000),
        ("01", "later", "2024-06-30", None, 300_000),
    ], columns=["cik", "accession", "period", "start", "dollars"])
    vendor = pd.DataFrame([
        ("01", "A", "2024-06-30", "2024-07-31", 0.2),
        ("01", "A", "2024-06-30", "2024-11-18", 0.3),
    ], columns=["cik", "gvkey", "period", "vintage", "atq"])
    verified = reconcile_assets(filings, facts, vendor)
    assert verified.accession.tolist() == ["first"]
    assert verified.usable.tolist() == [pd.Timestamp("2024-08-01")]
    conflicted = pd.concat([facts, facts.iloc[:1].assign(dollars=250_000)])
    assert reconcile_assets(filings, conflicted, vendor).empty


def test_q4_requires_same_context_and_later_availability():
    annual = dict(gvkey="A", cik="01", fiscal_year=2024, currency="USD",
                  basis="GAAP", start="2024-01-01", period="2024-12-31",
                  value=40, usable="2025-02-01", accession="annual")
    interim = dict(annual, period="2024-09-30", value=25, usable="2024-11-01",
                   accession="interim")
    assert fourth_quarter(annual, interim) == {
        "value": 15, "usable": "2025-02-01", "inputs": ("annual", "interim"),
    }
    assert fourth_quarter(annual, dict(interim, basis="other")) is None


def test_cap_requires_every_common_class():
    classes = pd.DataFrame([
        ("2024-06-27", 1, 10, 10, 100),
        ("2024-06-27", 1, 11, 20, 50),
        ("2024-06-27", 2, 12, 20, 50),
    ], columns=["session", "permco", "permno", "price", "shares"])
    expected = pd.DataFrame([("2024-06-27", 2, 13)], columns=["session", "permco", "permno"])
    expected = pd.concat([classes[["session", "permco", "permno"]], expected])
    caps = aggregate_market_cap(classes, expected)
    assert caps.cap.iloc[0] == 2000
    assert pd.isna(caps.cap.iloc[1])


def test_sampling_is_seeded_stratified_and_keeps_mandatory_cases():
    frame = pd.DataFrame({
        "audit_id": range(240),
        "disposition": ["accepted"] * 160 + ["rejected"] * 80,
        "stratum": [n % 4 for n in range(240)],
        "mandatory": [n in (10, 190) for n in range(240)],
    })
    sample = freeze_audit_sample(frame)
    assert sample.equals(freeze_audit_sample(frame.iloc[::-1]))
    assert sample.disposition.value_counts().to_dict() == {"accepted": 120, "rejected": 40}
    assert set(sample.loc[sample.mandatory, "audit_id"]) == {10, 190}
    audit = sample[["audit_id"]].assign(resolved=True, cap_error=0.01)
    metrics = {"overall": 0.80, "year": dict.fromkeys(range(2016, 2025), 0.70),
               "size_tercile": dict.fromkeys((1, 2, 3), 0.60),
               "delisting": {"denominator": 1, "rate": 0.60}}
    assert assess_gate(metrics, audit, sample)["decision"] == "pass"
    assert assess_gate(dict(metrics, overall=0.79), audit, sample)["decision"] == "fail"
    audit.loc[0, "cap_error"] = 0.011
    assert assess_gate(metrics, audit, sample)["decision"] == "blocked"


def test_link_admission_requires_two_anchors_known_on_prior_session():
    signal = pd.Timestamp("2024-08-30")
    prior = pd.Timestamp("2024-08-29")
    roster = pd.DataFrame({"signal": [signal, signal], "prior_session": [prior, prior],
                           "permno": [1, 2]})
    windows = pd.DataFrame([
        (signal, 1, "A", "01", "2023-01-01", "2024-12-31"),
        (signal, 2, "B", "02", "2024-01-01", "2024-12-31"),
    ], columns=["signal", "permno", "gvkey", "cik", "start", "stop"])
    anchors = pd.DataFrame([
        ("A", "01", "2024-03-31", prior), ("A", "01", "2024-06-30", signal),
        ("B", "02", "2023-12-31", prior), ("B", "02", "2024-06-30", prior),
    ], columns=["gvkey", "cik", "period", "usable"])
    assert admit_links(roster, windows, anchors).gvkey.isna().all()
    anchors.loc[1, "usable"] = prior
    assert admit_links(roster, windows, anchors).gvkey.fillna("").tolist() == ["A", ""]


def test_amendment_timing_and_frozen_denominator():
    dates = pd.to_datetime(["2024-08-30", "2024-11-29", "2024-12-31"])
    roster = pd.DataFrame({
        "signal": dates, "permno": [1, 1, 2], "gvkey": ["A", "A", None],
        "cik": ["01", "01", None],
        "prior_session": pd.to_datetime(["2024-08-29", "2024-11-27", "2024-12-30"]),
        "cap": [100, 100, float("nan")], "size_tercile": [1, 2, 3],
        "cap_session": pd.to_datetime(["2024-08-29", "2024-11-27", None]),
        "admitted_from": pd.to_datetime(["2024-08-29", "2024-08-29", None]),
        "start": ["2023-01-01", "2023-01-01", None],
        "stop": ["2024-12-31", "2024-12-31", None],
        "delist_date": pd.to_datetime([None] * 3),
    })
    base = dict(gvkey="A", cik="01", fiscal_quarter=2, currency="USD",
                basis="GAAP", fiscal_year_end="12", book_equity=-10,
                form="10-Q", net_income_accessions=("test",))
    facts = pd.DataFrame([
        dict(base, fiscal_year=2023, period="2023-06-30", assets=50, net_income=2,
             accepted_at="2023-07-31T21:00Z", usable="2023-08-02", accession="year-ago",
             net_income_start="2023-04-01"),
        dict(base, fiscal_year=2024, period="2024-06-30", assets=100, net_income=3,
             accepted_at="2024-07-30T21:00Z", usable="2024-07-31", accession="original",
             net_income_start="2024-04-01"),
        dict(base, fiscal_year=2024, period="2024-06-30", assets=125, net_income=5,
             accepted_at="2024-11-18T17:08Z", usable="2024-11-29", accession="amendment",
             net_income_start="2024-04-01", form="10-Q/A"),
    ])
    facts["accepted_at"] = pd.to_datetime(facts.accepted_at, utc=True)
    for column in ("period", "usable", "net_income_start"):
        facts[column] = pd.to_datetime(facts[column])
    panel = build_features(roster, facts)
    assert panel.accession.tolist() == ["original", "original", None]
    assert panel.asset_growth.iloc[0] == 1
    assert panel.negative_book_equity.tolist() == [True, True, False]
    assert coverage(panel)["complete"] == 2
    facts.loc[2, "usable"] = pd.Timestamp("2024-11-27")
    assert build_features(roster, facts).accession.iloc[1] == "amendment"
    for column, value, error in [
        ("prior_session", pd.Timestamp("2024-11-29"), "immediately precede"),
        ("cap_session", pd.Timestamp("2024-11-26"), "Market cap"),
    ]:
        invalid = roster.copy()
        invalid.loc[1, column] = value
        with pytest.raises(ValueError, match=error):
            build_features(invalid, facts)
    for column, value, error in [
        ("usable", pd.Timestamp("2024-11-18"), "precedes filing"),
        ("net_income_start", pd.Timestamp("2024-01-01"), "cover one quarter"),
    ]:
        invalid = facts.copy()
        invalid.loc[2, column] = value
        with pytest.raises(ValueError, match=error):
            build_features(roster, invalid)
    stale = roster.iloc[[1]].assign(signal=pd.Timestamp("2024-12-31"),
                                    prior_session=pd.Timestamp("2024-12-30"),
                                    cap_session=pd.Timestamp("2024-12-30"))
    assert build_features(stale, facts).status.tolist() == ["stale_filing"]
    roster.loc[2, "signal"] = pd.Timestamp("2025-01-31")
    with pytest.raises(ValueError, match="Confirmation"):
        build_features(roster, facts)
