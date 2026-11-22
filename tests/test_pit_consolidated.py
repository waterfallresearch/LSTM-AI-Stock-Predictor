"""Tests for the consolidated-RIC fallback candidates and the venue-volume fallback."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "TrainingData"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "TrainingData" / "pit"))
from pit.consolidated import add_volume_fallback  # noqa: E402
from lseg_consolidated import fallback_candidates  # noqa: E402


def test_fallback_candidates_try_k_first_and_keep_suffix():
    assert fallback_candidates("ABBV.N") == ["ABBV.K", "ABBV.O"]
    assert fallback_candidates("TGNA.N^C26") == ["TGNA.K^C26", "TGNA.O^C26"]
    assert fallback_candidates("SIVB.OQ^C23") == ["SIVB.K^C23", "SIVB^C23"]


def _panel(n=40):
    s = pd.bdate_range("2020-01-02", periods=n).strftime("%Y-%m-%d")
    rows = []
    for isin, ric, cons in [("A", "AAA.N", True), ("B", "BBB.N", True), ("C", "CCC.N^X20", False)]:
        for i, d in enumerate(s):
            v = 1000.0 + 10 * i
            rows.append({"session": d, "isin": isin, "ric": ric, "volume_venue": v,
                         "volume_consolidated": 3 * v if cons else np.nan, "valid_bar": True, "member": True})
    return pd.DataFrame(rows)


def test_venue_scaled_volume_uses_other_securities_ratio():
    out, audit = add_volume_fallback(_panel())
    c = out[out["isin"] == "C"]
    late = c.iloc[15:]                                        # after min_periods of the ratio window
    assert (late.volume_source == "venue_scaled").all()
    np.testing.assert_allclose(late.volume_adv, 3 * late.volume_venue)
    a = out[out["isin"] == "A"]
    assert (a.volume_source == "consolidated").all() and (a.volume_adv == a.volume_consolidated).all()
    assert audit["adv21_abs_log_error_median"] < 1e-9


def test_ratio_is_causal():
    p = _panel()
    p.loc[(p["isin"] != "C") & (p.session >= p.session.unique()[30]), "volume_consolidated"] *= 10  # later regime
    out, _ = add_volume_fallback(p)
    c = out[out["isin"] == "C"].reset_index(drop=True)
    np.testing.assert_allclose(c.volume_adv.iloc[15:30], 3 * c.volume_venue.iloc[15:30])  # unaffected by the future
