import numpy as np
import pandas as pd

from pit_model_label_dates import eligible_labels, fold_samples, realization_dates
from pit_walk_forward import HORIZONS


def test_label_end_uses_valid_bars_before_feature_filtering():
    bars = pd.bdate_range("2020-01-01", periods=140).delete(3)
    ends = realization_dates(bars, pd.Series([bars[0], bars[-1]]))
    assert ends.loc[0, "6m"] == bars[126]
    targets = pd.DataFrame(1.0, index=ends.index, columns=ends.columns)
    eligible = eligible_labels(targets, ends, bars[126])
    assert not eligible.loc[0, "6m"]
    assert not eligible.loc[1].any()


def test_cross_boundary_outlier_cannot_set_threshold_or_enter_training():
    dates = pd.bdate_range("2020-01-01", periods=300)
    frame = pd.DataFrame({"Date": dates, "member": True})
    targets = pd.DataFrame(0.0, index=frame.index, columns=HORIZONS)
    targets.loc[60, "6m"] = 100.0
    targets.loc[81, "6m"] = 1.0
    ends = pd.DataFrame({h: dates + pd.Timedelta(days=1) for h in HORIZONS})
    ends.loc[60, "6m"] = dates[150]
    fold = {"train_end": dates[120], "val_start": dates[150],
            "val_end": dates[210], "test_start": dates[250]}
    labels, training, validation = fold_samples(frame, targets, ends, fold)
    assert 60 not in training
    assert 81 in training and labels.loc[81, "6m"] == 1.0
    assert np.all(frame.Date.iloc[validation] >= fold["val_start"])
