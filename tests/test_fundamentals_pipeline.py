import pandas as pd
import pytest

from TrainingData.pit.fundamentals_pipeline import (
    load_crsp_daily, load_snapshot, market_inputs, reconcile_vintages,
)
from TrainingData.pit.fundamentals_features import build_features


def test_browser_snapshot_contract_and_causal_amendment(tmp_path):
    path = tmp_path / "snapshot.htm"
    headings = [
        "Global Company Key", "Data Date", "Point Date", "Fiscal Year-end Month",
        "Assets - Total", "CommonOrdinary Equity - Total", "Net Income (Loss)",
        "Level of Consolidation", "Industry Format", "Data Format", "Currency Code - Interim Issue",
    ]
    raw = [["012181", "2024-06-30", "2024-07-30", 12, 2861.924, 1986.362, 3.321, "C", "INDL", "STD", "USD"],
           ["012181", "2024-06-30", "2024-11-12", 12, 2865, 1985, 6.914, "C", "INDL", "STD", "USD"],
           ["012181", "2024-06-30", "2024-11-28", 12, 2866.006, 1984.438, 5.713, "C", "INDL", "STD", "USD"]]
    html = "<table><tr><th colspan='11'>Snapshot</th></tr>"
    html += "<tr>" + "".join(f"<th>{heading}</th>" for heading in headings) + "</tr>"
    html += "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in line) + "</tr>" for line in raw)
    path.write_text(html + "</table>")
    snapshots = load_snapshot([path])
    assert snapshots.gvkey.unique().tolist() == ["012181"]
    context = pd.DataFrame([
        ("original", "10-Q", "2024-07-30T21:04:52Z", 2861924000, 1986362000, 3321000),
        ("amended", "10-Q/A", "2024-11-18T17:08:36Z", 2866006000, 1984438000, 5713000),
    ], columns=["accession", "form", "accepted_at", "assets", "parent_equity", "income"]).assign(
        gvkey="012181", cik="0000730272", currency="USD", consolidated=True, fiscal_year=2024,
        fiscal_quarter=2, fiscal_year_end=12, basis="GAAP", preferred=0,
        preferred_verified=True, income_type="quarter", income_start=pd.Timestamp("2024-04-01"),
        period=pd.Timestamp("2024-06-30"),
    )
    context["accepted_at"] = pd.to_datetime(context.accepted_at, utc=True)
    verified, rejected = reconcile_vintages(snapshots, context)
    assert rejected.empty
    assert verified.usable.tolist() == list(pd.to_datetime(["2024-07-31", "2024-11-29"]))
    assert verified.net_income.tolist() == [3321000, 5713000]
    roster = pd.DataFrame({
        "signal": pd.to_datetime(["2024-08-30", "2024-11-29"]),
        "prior_session": pd.to_datetime(["2024-08-29", "2024-11-27"]), "permno": [1, 1],
    }).assign(gvkey="012181", cik="0000730272", start="2023-01-01", stop="2024-12-31",
              admitted_from=pd.Timestamp("2024-08-01"))
    listing = pd.DataFrame({"permno": [1, 2], "permco": [10, 10],
                            "start": ["2023-01-01"] * 2, "stop": ["2024-12-31"] * 2})
    quotes = pd.DataFrame([
        ("2024-08-29", 1, 10, 20.0, 10.0), ("2024-08-29", 2, 10, 10.0, 5.0),
        ("2024-11-27", 1, 10, 30.0, 10.0),
    ], columns=["session", "permno", "permco", "price", "shrout"])
    delists = pd.DataFrame({"permno": [1], "delist_date": ["2024-12-10"]})
    ready = market_inputs(roster, listing, quotes, delists)
    assert ready.cap.iloc[0] == 250000
    assert pd.isna(ready.cap.iloc[1])
    panel = build_features(ready, verified)
    assert panel.accession.tolist() == ["original", "original"]
    assert panel.profitability.iloc[0] == pytest.approx(3321000 / 2861924000)
    assert pd.isna(panel.book_to_market.iloc[1])


def test_snapshot_rejects_protected_point_dates(tmp_path):
    path = tmp_path / "snapshot.csv"
    path.write_text(
        "gvkey,period,vintage,fiscal_year_end,atq,ceqq,niq,consol,indfmt,datafmt,currency\n"
        "012181,2024-06-30,2025-01-02,12,1,2,3,C,INDL,STD,USD\n"
    )
    with pytest.raises(ValueError, match="Confirmation date"):
        load_snapshot([path])


def test_wrds_missing_amount_is_not_zero(tmp_path):
    path = tmp_path / "snapshot.csv"
    path.write_text(
        "gvkey,period,vintage,fiscal_year_end,atq,ceqq,niq,consol,indfmt,datafmt,currency\n"
        "012181,2024-06-30,2024-07-30,12,1,.,0,C,INDL,STD,USD\n"
    )
    row = load_snapshot([path]).iloc[0]
    assert pd.isna(row.ceqq)
    assert row.niq == 0


def test_crsp_export_keeps_unpriced_common_class_as_missing(tmp_path):
    path = tmp_path / "crsp_daily.csv.gz"
    pd.DataFrame([
        (1, 7, "2016-01-28", "2010-01-01", "2016-01-31", "EQTY", "COM", 94.09, "TR", 5544583),
        (2, 7, "2016-01-28", "2010-01-01", "2016-01-31", "EQTY", "COM", 23.0, "XX", 200),
    ], columns=["PERMNO", "PERMCO", "DlyCalDt", "SecInfoStartDt", "SecInfoEndDt",
                "SecurityType", "SecuritySubType", "DlyPrc", "DlyPrcFlg", "ShrOut"]).to_csv(path, index=False)
    result = load_crsp_daily([path], pd.to_datetime(["2016-01-28"]))
    assert result.permno.tolist() == [1, 2]
    assert result.price.iloc[0] == 94.09
    assert pd.isna(result.price.iloc[1])
    assert result.shrout.iloc[0] == 5544583


def test_snapshot_quarantines_competing_point_date_rows(tmp_path):
    path = tmp_path / "snapshot.csv.gz"
    pd.DataFrame([
        ("012181", "2024-06-30", "2024-07-30", 12, 100, 50, 10, "C", "INDL", "STD", "USD"),
        ("012181", "2024-06-30", "2024-07-30", 12, 100, 50, 20, "C", "INDL", "STD", "USD"),
        ("012181", "2024-06-30", "2024-07-31", 12, 100, 50, 10, "C", "INDL", "STD", "USD"),
    ], columns=["GVKEY", "datadate", "pointdate", "fyr", "ATQ", "CEQQ", "NIQ",
                "CONSOL", "INDFMT", "DATAFMT", "CURCDQ"]).to_csv(path, index=False)
    quarantine = []
    assert load_snapshot([path], quarantined=quarantine).vintage.tolist() == [pd.Timestamp("2024-07-31")]
    assert len(quarantine) == 1
    assert quarantine[0]["reason"] == "competing_wrds_point_date"
