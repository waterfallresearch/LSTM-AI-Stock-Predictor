"""Fit the two preregistered tabular models on corrected development folds."""
from __future__ import annotations

import argparse
import json
import warnings
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

import pit_panel
import pit_walk_forward as pit_wf
from pit_model_label_dates import experiment_provenance, is_resumable, model_fold

ROOT = pit_wf.OUT / "model_comparison"


def estimators(arm: str, year: int, threads: int):
    if arm == "logistic":
        from sklearn.linear_model import LogisticRegression

        return [LogisticRegression(C=0.1, solver="lbfgs", max_iter=1000, tol=0.0001)]

    from lightgbm import LGBMClassifier

    return [
        LGBMClassifier(
            objective="binary", boosting_type="gbdt", n_estimators=300, learning_rate=0.05,
            num_leaves=31, max_depth=-1, min_child_samples=500, colsample_bytree=0.5,
            subsample=0.8, subsample_freq=1, max_bin=255, deterministic=True,
            force_col_wise=True, random_state=1000 * year + seed, n_jobs=threads, verbosity=-1,
        )
        for seed in range(3)
    ]


def fit_arm(arm, shared, fold, year, threads, spec, provenance):
    from sklearn.exceptions import ConvergenceWarning

    train = shared.train_x.reshape(len(shared.train_x), -1)
    models = {}
    for j, horizon in enumerate(pit_wf.HORIZONS):
        fits = estimators(arm, year, threads)
        with warnings.catch_warnings():
            warnings.simplefilter("error", ConvergenceWarning)
            for model in fits:
                model.fit(train, shared.train_y[:, j])
        models[horizon] = fits

    output = ROOT / arm
    output.mkdir(parents=True, exist_ok=True)
    for split, start, end in (
        ("val", fold["val_start"], fold["val_end"]),
        ("test", fold["test_start"], fold["test_end"] + pd.Timedelta(days=1)),
    ):
        parts = []
        for isin, (features, labels, dates, member) in shared.cache.items():
            eligible = member & (dates >= np.datetime64(start)) & (dates < np.datetime64(end))
            positions = np.flatnonzero(eligible)
            positions = positions[positions >= pit_wf.WINDOW]
            if not len(positions):
                continue
            windows = pit_wf.wf.windows(features, positions).reshape(len(positions), -1)
            frame = pd.DataFrame({"Date": dates[positions], "isin": isin})
            for j, (horizon, fits) in enumerate(models.items()):
                frame[f"Pred_Prob_{horizon}"] = np.mean(
                    [model.predict_proba(windows)[:, 1] for model in fits], axis=0,
                )
                frame[f"Class_{horizon}"] = labels[positions, j]
            parts.append(frame)
        pd.concat(parts, ignore_index=True).to_csv(output / f"Y{year}_{split}.csv.gz", index=False)
    metadata = {
        "arm": arm, "year": year, "sample_digests": shared.digests,
        "provenance": provenance,
        "feature_indices": shared.feature_indices.tolist(),
        "n_train": len(shared.train_y), "n_val": len(shared.validation_y),
        "train_pos_rate": shared.train_y.mean(axis=0).tolist(),
        "features_sha256": spec["features_sha256"],
        "features_file_sha256": spec["features_file_sha256"],
        "shared_code_sha256": pit_wf.file_sha(Path(__file__).with_name("pit_model_label_dates.py")),
        "code_sha256": pit_wf.file_sha(Path(__file__)),
        "versions": {name: version(name) for name in (
            ["numpy", "pandas", "scikit-learn"] + (["lightgbm"] if arm == "lightgbm" else [])
        )},
        "parameters": [model.get_params() for model in next(iter(models.values()))],
    }
    (output / f"Y{year}.json").write_text(json.dumps(metadata, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", default="2016-2024")
    parser.add_argument("--arm", choices=["logistic", "lightgbm"], required=True)
    parser.add_argument("--threads", type=int, default=5)
    args = parser.parse_args()
    years = pit_wf.wf.parse_years(args.years)
    if not years or any(year not in range(2016, 2025) for year in years):
        parser.error("only the registered 2016–2024 development folds are allowed")
    data, spec = pit_wf.load_frozen()
    provenance = experiment_provenance(spec, Path(__file__))
    panel = pit_panel.load_pit(end=pit_wf.END, strict=True)
    for year in years:
        output = ROOT / args.arm
        forecasts = tuple(output / f"Y{year}_{split}.csv.gz" for split in ("val", "test"))
        if is_resumable(output / f"Y{year}.json", forecasts, provenance):
            continue
        fold = pit_wf.wf.fold_dates(year, panel.spy.index)
        fit_arm(args.arm, model_fold(data, panel, fold), fold, year, args.threads, spec, provenance)
        print(f"{args.arm} {year} complete", flush=True)


if __name__ == "__main__":
    main()
