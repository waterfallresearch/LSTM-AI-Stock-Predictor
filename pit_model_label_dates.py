"""Recover and audit target realization dates for the model comparison."""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

import pit_walk_forward as pit_wf


def experiment_provenance(spec, runner: Path) -> dict:
    files = {runner.resolve(), *(pit_wf.ROOT / name for name in (
        "pit_model_label_dates.py", "pit_walk_forward.py", "walk_forward.py", "pit_panel.py",
    ))}
    files.update((pit_wf.ROOT / "TrainingData" / "pit").glob("*.py"))
    return {
        "features_sha256": spec["features_sha256"],
        "features_file_sha256": spec["features_file_sha256"],
        "source_hashes": {path.name: pit_wf.file_sha(path) for path in sorted(files)},
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=pit_wf.ROOT, text=True).strip(),
        "git_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=pit_wf.ROOT)),
    }


def is_resumable(metadata: Path, forecasts: tuple[Path, ...], provenance: dict) -> bool:
    if not metadata.exists():
        return False
    recorded = json.loads(metadata.read_text())
    if recorded.get("provenance") != provenance or any(not path.is_file() for path in forecasts):
        raise RuntimeError(f"Stale or incomplete comparison outputs: {metadata}")
    return True


def realization_dates(valid_bars: pd.DatetimeIndex, feature_dates: pd.Series) -> pd.DataFrame:
    """Compute target ends before dropping bars for missing features."""
    bar_dates = pd.Series(valid_bars, index=valid_bars)
    return pd.DataFrame({
        horizon: bar_dates.shift(-sessions).reindex(feature_dates).to_numpy()
        for horizon, sessions in zip(pit_wf.HORIZONS, pit_wf.HORIZON_DAYS)
    }, index=feature_dates.index)


def eligible_labels(
    targets: pd.DataFrame, ends: pd.DataFrame, boundary: pd.Timestamp
) -> pd.DataFrame:
    """Return the per-horizon mask for outcomes known before the boundary."""
    if not targets.index.equals(ends.index) or not targets.columns.equals(ends.columns):
        raise ValueError("Target values and realization dates must align")
    return targets.notna() & ends.lt(boundary)


def targets_and_dates(bars: pd.DataFrame, frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Validate the recovered label definition against the frozen feature file."""
    valid = bars.loc[bars.AdjClose.notna()]
    targets = frame[[f"Target_{h}" for h in pit_wf.HORIZONS]].copy()
    targets.columns = pit_wf.HORIZONS
    for horizon, sessions in zip(pit_wf.HORIZONS, pit_wf.HORIZON_DAYS):
        total_return = valid.TrClose
        reconstructed = np.log(total_return.shift(-sessions) / total_return).reindex(frame.Date)
        np.testing.assert_allclose(targets[horizon], reconstructed, rtol=1e-10, atol=1e-12)
    return targets, realization_dates(valid.index, frame.Date)


def fold_samples(frame, targets, ends, fold):
    """Return forecast labels and the eligible training and validation positions."""
    if frame.member.dtype != np.dtype(bool):
        raise ValueError("Frozen membership must be a non-nullable boolean column")
    training = frame.Date.lt(fold["train_end"])
    train_mask = eligible_labels(targets, ends, fold["val_start"])
    val_mask = eligible_labels(targets, ends, fold["test_start"])
    # The registered threshold uses all training-period rows, before membership and stride.
    threshold_targets = targets.where(train_mask).loc[training]
    thresholds = threshold_targets.mean() + threshold_targets.std()
    labels = targets.gt(thresholds).astype(np.float32).where(targets.notna() & thresholds.notna())
    if training.sum() < 100:
        labels.loc[:, :] = np.nan
    stride = np.arange(pit_wf.WINDOW, len(frame), pit_wf.TRAIN_STEP)
    candidates = stride[frame.member.iloc[stride].to_numpy() & labels.iloc[stride].notna().all(axis=1)]
    validation = frame.Date.ge(fold["val_start"]) & frame.Date.lt(fold["val_end"])
    tr = candidates[(training & train_mask.all(axis=1)).iloc[candidates].to_numpy()]
    va = candidates[(validation & val_mask.all(axis=1)).iloc[candidates].to_numpy()]
    for sample, boundary in [(tr, fold["val_start"]), (va, fold["test_start"])]:
        if not ends.iloc[sample].lt(boundary).all(axis=None):
            raise RuntimeError("An eligible target crosses the next fold boundary")
    return labels, tr, va


@dataclass(frozen=True)
class ModelFold:
    train_x: np.ndarray
    train_y: np.ndarray
    validation_x: np.ndarray
    validation_y: np.ndarray
    cache: dict
    feature_indices: np.ndarray
    digests: dict


def model_fold(data, panel, fold) -> ModelFold:
    """Materialize identical training inputs for the sequence and flattened models."""
    from sklearn.preprocessing import StandardScaler

    rows = {}
    for isin in sorted(data):
        frame = data[isin]
        targets, ends = targets_and_dates(panel.adjusted[isin], frame)
        labels, train, validation = fold_samples(frame, targets, ends, fold)
        in_validation = frame.Date.ge(fold["val_start"]) & frame.Date.lt(fold["val_end"])
        labels.loc[in_validation] = labels.loc[in_validation].where(
            ends.loc[in_validation].lt(fold["test_start"])
        )
        in_test = frame.Date.ge(fold["test_start"])
        labels.loc[in_test] = labels.loc[in_test].where(
            ends.loc[in_test].le(pd.Timestamp(pit_wf.END))
        )
        rows[isin] = (labels, train, validation)
    endpoints = np.concatenate([
        data[isin].iloc[train][pit_wf.FEATURES].to_numpy(dtype=np.float64)
        for isin, (_, train, _) in rows.items() if len(train)
    ])
    feature_indices = np.flatnonzero(endpoints.std(axis=0) > 1e-12)
    scaler = StandardScaler().fit(endpoints[:, feature_indices])
    del endpoints

    cache = {}
    batches = {split: ([], [], hashlib.sha256()) for split in ("train", "validation")}
    for isin, (labels, train, validation) in rows.items():
        frame = data[isin]
        features = frame[pit_wf.FEATURES].to_numpy(dtype=np.float64)[:, feature_indices]
        features = scaler.transform(features).astype(np.float32)
        y = labels.to_numpy(dtype=np.float32)
        cache[isin] = (features, y, frame.Date.to_numpy(), frame.member.to_numpy())
        for split, positions in (("train", train), ("validation", validation)):
            if not len(positions):
                continue
            xs, ys, digest = batches[split]
            xs.append(pit_wf.wf.windows(features, positions))
            ys.append(y[positions])
            keys = labels.iloc[positions].assign(isin=isin, date=frame.Date.iloc[positions])
            digest.update(pd.util.hash_pandas_object(keys, index=False).to_numpy(dtype="<u8").tobytes())
    tx, ty, _ = batches["train"]
    vx, vy, _ = batches["validation"]
    return ModelFold(
        np.concatenate(tx), np.concatenate(ty), np.concatenate(vx), np.concatenate(vy),
        cache, feature_indices, {split: digest.hexdigest() for split, (_, _, digest) in batches.items()},
    )


def main() -> None:
    import pit_panel

    data, _ = pit_wf.load_frozen()
    panel = pit_panel.load_pit(end=pit_wf.END, strict=True)
    calendar = panel.spy.index
    folds = {year: pit_wf.wf.fold_dates(year, calendar) for year in range(2016, 2025)}
    counts = {year: [0, 0] for year in folds}
    digests = {year: [hashlib.sha256(), hashlib.sha256()] for year in folds}
    for isin in sorted(data):
        frame = data[isin]
        targets, ends = targets_and_dates(panel.adjusted[isin], frame)
        for year, fold in folds.items():
            labels, tr, va = fold_samples(frame, targets, ends, fold)
            for split, positions in enumerate((tr, va)):
                keys = labels.iloc[positions].assign(isin=isin, date=frame.Date.iloc[positions])
                hashes = pd.util.hash_pandas_object(keys, index=False).to_numpy(dtype="<u8")
                digests[year][split].update(hashes.tobytes())
                counts[year][split] += len(positions)
    for year, (train, validation) in counts.items():
        print(json.dumps({
            "year": year, "train": train, "validation": validation,
            "pandas": pd.__version__,
            "train_digest": digests[year][0].hexdigest(),
            "validation_digest": digests[year][1].hexdigest(),
        }), flush=True)


if __name__ == "__main__":
    main()
