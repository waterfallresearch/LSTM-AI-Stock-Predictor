"""Walk-forward LSTM on the point-in-time S&P 500 universe.
Design: research/pit_nextopen_2026-11-20_preregistration.md (frozen). The model, fold windows, seeds, labels and
thresholds are those of walk_forward.py; only the data source and the feature list differ, as preregistered.

    python pit_walk_forward.py prepare                 # build + freeze features (wf_pit/features.parquet, feature_spec.json)
    python pit_walk_forward.py job --year 2016 --seed-index 0
    python pit_walk_forward.py run --years 2016-2024 --seeds 3 --workers 3 --threads 5
Outputs are resumable (a job whose meta JSON exists is skipped): wf_pit/forecasts/Y{year}_s{k}_{val|test}.csv.gz,
wf_pit/meta/Y{year}_s{k}.json, wf_pit/logs/. `run` can simply be restarted after the machine sleeps or reboots.

Feature notes (fixed before fold 1; the sha256 of FEATURES is recorded in feature_spec.json and in every job's meta):
- Computed per security on split-adjusted PIT bars (pit_panel adjusted AdjOpen/AdjHigh/AdjLow/AdjClose, AdjVolume
  from volume_adv), over that security's valid bars only (the 170 invalid bars to 2024 are skipped, as the old
  processor's input simply lacked them).
- Same formulas as TrainingData/processor.py process_file. Price-level features (YesterdayClose, MAs, EMAs,
  Bollinger bands) are expressed relative to the close as walk_forward.py did, and MACD / MACD_Signal are divided by
  the close too: adjusted LEVELS embed later splits (pit_panel docstring), so only scale-invariant forms are allowed.
- Excluded: OBV (excluded before), abnormal_volume_z (an exact duplicate of abnormal_vol), calendar fields (not OHLCV),
  and all alternative data, as preregistered.
- SPY features from spy_pit.csv tr_index: 1/5/20-session log returns and 20-session volatility.
- Labels: forward log return of the total-return adjusted close (TrClose) over 1/5/21/126 valid sessions; NaN when
  the window runs past the security's last valid bar (such rows are dropped from training and counted).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

import walk_forward as wf

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "wf_pit"
END = "2024-12-31"
HORIZONS, HORIZON_DAYS = wf.HORIZONS, wf.HORIZON_DAYS
WINDOW, TRAIN_STEP = wf.WINDOW, wf.TRAIN_STEP

FEATURES = [
    "YesterdayClose", "YesterdayOpenLogR", "YesterdayHighLogR", "YesterdayLowLogR", "YesterdayVolumeLogR",
    "YesterdayCloseLogR", "MA10", "MA20", "MA30", "MA50", "MA200", "EMA10", "EMA30", "RSI", "MACD", "MACD_Signal",
    "BollingerUpper", "BollingerLower", "Volatility_10", "Volatility_20", "Volatility_30", "ZScore",
    "overnight_gap", "abnormal_vol", "volatility_5d", "volatility_20d", "momentum_5d", "momentum_20d", "skew_5d",
    "intraday_range", "spy_ret_1d", "spy_ret_5d", "spy_ret_20d", "spy_vol_20d",
]
REL_TO_CLOSE = ["YesterdayClose", "MA10", "MA20", "MA30", "MA50", "MA200", "EMA10", "EMA30", "MACD", "MACD_Signal",
                "BollingerUpper", "BollingerLower"]


def features_sha() -> str:
    return hashlib.sha256(json.dumps(FEATURES).encode()).hexdigest()


def file_sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ----------------------------------------------------------------------------- features

def security_features(a: pd.DataFrame) -> pd.DataFrame:
    """a: one security's adjusted frame (index Date; AdjOpen AdjHigh AdjLow AdjClose TrClose AdjVolume), valid rows.
    Formulas copied from processor.process_file; every value at t uses bars <= t only (labels excepted)."""
    o, h, l, c, v = (a[k] for k in ["AdjOpen", "AdjHigh", "AdjLow", "AdjClose", "AdjVolume"])
    v = v.where(v > 0)
    d = pd.DataFrame(index=a.index)
    d["YesterdayClose"] = c.shift(1)
    d["YesterdayOpenLogR"] = np.log(o / o.shift(1))
    d["YesterdayHighLogR"] = np.log(h / h.shift(1))
    d["YesterdayLowLogR"] = np.log(l / l.shift(1))
    d["YesterdayVolumeLogR"] = np.log(v / v.shift(1))
    d["YesterdayCloseLogR"] = np.log(c / c.shift(1))
    for n in (10, 20, 30, 50, 200):
        d[f"MA{n}"] = c.rolling(n).mean()
    d["EMA10"] = c.ewm(span=10, adjust=False).mean()
    d["EMA30"] = c.ewm(span=30, adjust=False).mean()
    delta = c.diff()
    avg_gain = delta.clip(lower=0).rolling(14).mean()
    avg_loss = (-delta).clip(lower=0).rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan).fillna(1e-10)
    d["RSI"] = 100 - 100 / (1 + rs)
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    d["MACD"] = macd
    d["MACD_Signal"] = macd.ewm(span=9, adjust=False).mean()
    ma20, sd20 = c.rolling(20).mean(), c.rolling(20).std()
    d["BollingerUpper"] = ma20 + 2 * sd20
    d["BollingerLower"] = ma20 - 2 * sd20
    r = c.pct_change()
    for n in (10, 20, 30):
        d[f"Volatility_{n}"] = r.rolling(n).std()
    d["ZScore"] = (c - ma20) / sd20
    d["overnight_gap"] = (o - c.shift(1)) / c.shift(1)
    rv = v.rolling(20)
    d["abnormal_vol"] = (v - rv.mean()) / rv.std().replace(0, np.nan).fillna(1e-10)
    d["volatility_5d"] = r.rolling(5).std() * np.sqrt(252)
    d["volatility_20d"] = r.rolling(20).std() * np.sqrt(252)
    d["momentum_5d"] = c / c.shift(5) - 1
    d["momentum_20d"] = c / c.shift(20) - 1
    d["skew_5d"] = r.rolling(5).skew()
    d["intraday_range"] = (h - l) / c
    for k in REL_TO_CLOSE:
        d[k] = d[k] / c - (0.0 if k in ("MACD", "MACD_Signal") else 1.0)
    tr = a["TrClose"]
    for hz, n in zip(HORIZONS, HORIZON_DAYS):
        d[f"Target_{hz}"] = np.log(tr.shift(-n) / tr)
    return d


def spy_features(spy: pd.DataFrame) -> pd.DataFrame:
    lr = np.log(spy["tr_index"] / spy["tr_index"].shift(1))
    return pd.DataFrame({"spy_ret_1d": lr, "spy_ret_5d": lr.rolling(5).sum(), "spy_ret_20d": lr.rolling(20).sum(),
                         "spy_vol_20d": lr.rolling(20).std() * np.sqrt(252)}, index=spy.index)


def prepare() -> None:
    import pit_panel as pp
    OUT.mkdir(exist_ok=True)
    pit = pp.load_pit(end=END, strict=True)
    spyf = spy_features(pit.spy)
    parts, dropped_warmup = [], 0
    for isin, a in pit.adjusted.items():
        f = pit.frames[isin]
        valid = a["AdjClose"].notna()
        a, mem = a[valid], f.loc[valid, "Member"]
        if len(a) < WINDOW + 2:
            continue
        d = security_features(a).join(spyf, how="left")
        d = d.replace([np.inf, -np.inf], np.nan)
        ok = d[FEATURES].notna().all(axis=1)
        dropped_warmup += int((~ok & mem).sum())
        d = d[ok]
        d.insert(0, "member", mem.reindex(d.index).astype(bool))
        d.insert(0, "isin", isin)
        parts.append(d.reset_index())
    df = pd.concat(parts, ignore_index=True)
    df[FEATURES] = df[FEATURES].astype(np.float32)
    path = OUT / "features.parquet"
    df.to_parquet(path, index=False)
    spec = {"features": FEATURES, "features_sha256": features_sha(), "features_file_sha256": file_sha(path),
            "code_sha256": file_sha(Path(__file__)), "end": END, "rows": len(df), "securities": int(df["isin"].nunique()),
            "member_rows": int(df["member"].sum()), "member_rows_dropped_warmup_or_missing": dropped_warmup,
            "data_report": {k: pit.report[k] for k in ["member_sessions", "member_sessions_volume_source",
                                                       "member_sessions_missing_volume"]},
            "frozen_utc": pd.Timestamp.now("UTC").isoformat()}
    (OUT / "feature_spec.json").write_text(json.dumps(spec, indent=1, default=str))
    print(json.dumps({k: v for k, v in spec.items() if k != "features"}, indent=1, default=str))


def load_frozen() -> tuple[dict[str, pd.DataFrame], dict]:
    spec = json.loads((OUT / "feature_spec.json").read_text())
    if spec["features_sha256"] != features_sha() or spec["features"] != FEATURES:
        raise RuntimeError("FEATURES changed after freezing; that is a new trial (re-run prepare deliberately).")
    if file_sha(OUT / "features.parquet") != spec["features_file_sha256"]:
        raise RuntimeError("features.parquet differs from the frozen file.")
    df = pd.read_parquet(OUT / "features.parquet")
    return {k: g.reset_index(drop=True) for k, g in df.groupby("isin", sort=True)}, spec


# ----------------------------------------------------------------------------- job

def run_job(year: int, k: int, threads: int, *, comparison: bool = False) -> None:
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    import tensorflow as tf
    from sklearn.metrics import roc_auc_score
    from sklearn.preprocessing import StandardScaler

    tf.config.threading.set_intra_op_parallelism_threads(threads)
    tf.config.threading.set_inter_op_parallelism_threads(2)
    seed = 1000 * year + k
    tf.keras.utils.set_random_seed(seed)
    tf.config.experimental.enable_op_determinism()
    t0 = time.time()

    data, spec = load_frozen()
    cal = pd.DatetimeIndex(sorted(pd.read_csv(ROOT / "TrainingData/indicators_data/pit/spy_pit.csv",
                                              parse_dates=["session"])["session"]))
    cal = cal[cal <= pd.Timestamp(END)]
    fd = wf.fold_dates(year, cal)
    te = np.datetime64(fd["train_end"])

    output = OUT / "model_comparison" / "lstm" if comparison else OUT
    if comparison:
        import pit_panel
        from pit_model_label_dates import experiment_provenance, model_fold

        pit = pit_panel.load_pit(end=END, strict=True)
        fd = wf.fold_dates(year, pit.spy.index)
        shared = model_fold(data, pit, fd)
        Xtr, ytr = shared.train_x, shared.train_y
        Xv, yv = shared.validation_x, shared.validation_y
        cache, feat_idx = shared.cache, shared.feature_indices
        for directory in ("forecasts", "meta"):
            (output / directory).mkdir(parents=True, exist_ok=True)
        sample_metadata = {"sample_digests": shared.digests, "corrected_labels": True,
                           "provenance": experiment_provenance(spec, Path(__file__)),
                           "feature_indices": feat_idx.tolist(),
                           "shared_code_sha256": file_sha(Path(__file__).with_name("pit_model_label_dates.py"))}
    else:
        thresholds, train_rows = {}, []
        for t, df in data.items():
            tr = df[df["Date"] < fd["train_end"]]
            if len(tr) >= 100:
                thresholds[t] = {h: float(tr[f"Target_{h}"].mean() + tr[f"Target_{h}"].std()) for h in HORIZONS}
                train_rows.append(tr.loc[tr["member"], FEATURES].to_numpy(np.float64))
        Xs = np.vstack(train_rows)
        keep = Xs.std(axis=0) > 1e-12
        feat_idx = np.flatnonzero(keep)
        scaler = StandardScaler().fit(Xs[:, keep])
        del Xs, train_rows

        def prep(df):
            f = df[FEATURES].to_numpy(np.float64)[:, feat_idx]
            return np.nan_to_num(scaler.transform(f), nan=0.0, posinf=10, neginf=-10).astype(np.float32)

        def labels(df, t):
            th = thresholds.get(t)
            y = np.full((len(df), 4), np.nan, np.float32)
            if th is not None:
                for j, h in enumerate(HORIZONS):
                    tg = df[f"Target_{h}"].to_numpy(float)
                    y[:, j] = np.where(np.isfinite(tg), (tg > th[h]).astype(float), np.nan)
            return y

        Xtr, ytr, Xv, yv, cache = [], [], [], [], {}
        dropped_label = 0
        for t, df in data.items():
            F, Y, d, m = prep(df), labels(df, t), df["Date"].to_numpy(), df["member"].to_numpy()
            cache[t] = (F, Y, d, m)
            base = np.arange(WINDOW, len(df), TRAIN_STEP)
            base = base[m[base]]
            lab_ok = np.all(np.isfinite(Y[base]), axis=1)
            in_tr = d[base] < te
            dropped_label += int((in_tr & ~lab_ok & (t in thresholds)).sum())
            tr_idx = base[in_tr & lab_ok]
            v_idx = base[(d[base] >= np.datetime64(fd["val_start"])) & (d[base] < np.datetime64(fd["val_end"])) & lab_ok]
            if len(tr_idx):
                Xtr.append(wf.windows(F, tr_idx)); ytr.append(Y[tr_idx])
            if len(v_idx):
                Xv.append(wf.windows(F, v_idx)); yv.append(Y[v_idx])
        Xtr, ytr, Xv, yv = map(np.concatenate, (Xtr, ytr, Xv, yv))
        sample_metadata = {"train_rows_dropped_label_past_last_bar": dropped_label,
                           "securities_with_threshold": len(thresholds)}
    t_data = time.time() - t0

    class EarlyStoppingWithWarmup(tf.keras.callbacks.EarlyStopping):
        def __init__(self, start_epoch=3, **kw):
            super().__init__(**kw)
            self.start_epoch = start_epoch

        def on_epoch_end(self, epoch, logs=None):
            if epoch >= self.start_epoch:
                super().on_epoch_end(epoch, logs)

    model = wf.build_model(len(feat_idx))
    es = EarlyStoppingWithWarmup(start_epoch=3, patience=8, monitor="val_auc", mode="max", restore_best_weights=True)
    rlr = tf.keras.callbacks.ReduceLROnPlateau(monitor="val_auc", mode="max", factor=0.5, patience=3, min_lr=1e-5)
    hist = model.fit(Xtr, ytr, validation_data=(Xv, yv), batch_size=128, epochs=100, callbacks=[es, rlr],
                     shuffle=True, verbose=2)
    if getattr(es, "best_weights", None) is not None:
        model.set_weights(es.best_weights)
    va = hist.history["val_auc"]
    best_epoch = int(np.argmax(va[3:]) + 3) if len(va) > 3 else int(np.argmax(va))
    t_fit = time.time() - t0 - t_data

    # MC dropout: 25 stochastic passes per row (dropout active), mean and std per horizon. Rows are batched across
    # securities through one compiled call (amendment 7: same estimator, about 10x faster than per-security eager calls).
    n_mc, test_auc = 25, {}
    mc_call = tf.function(lambda x: model(x, training=True), reduce_retracing=True,
                          input_signature=[tf.TensorSpec([None, WINDOW + 1, len(feat_idx)], tf.float32)])
    CHUNK, BATCH = 16384, 4096
    for split, lo, hi in [("val", fd["val_start"], fd["val_end"]),
                          ("test", fd["test_start"], fd["test_end"] + pd.Timedelta(days=1))]:
        keys = []
        for t, (F, Y, d, m) in cache.items():
            idx = np.arange(WINDOW, len(d))
            idx = idx[(d[idx] >= np.datetime64(lo)) & (d[idx] < np.datetime64(hi)) & m[idx]]
            if len(idx):
                keys.append((t, idx))
        rows, buf, n_buf = [], [], 0

        def flush(buf):
            X = np.concatenate([wf.windows(cache[t][0], idx) for t, idx in buf])
            preds = np.stack([np.concatenate([mc_call(X[i:i + BATCH]).numpy() for i in range(0, len(X), BATCH)])
                              for _ in range(n_mc)])
            mean, std = preds.mean(0), preds.std(0)
            o = 0
            for t, idx in buf:
                n = len(idx)
                _, Y, d, _ = cache[t]
                rec = {"Date": d[idx], "isin": t}
                for j, h in enumerate(HORIZONS):
                    rec[f"Pred_Prob_{h}"] = mean[o:o + n, j]
                    rec[f"Pred_Prob_Std_{h}"] = std[o:o + n, j]
                    rec[f"Class_{h}"] = Y[idx, j]
                rows.append(pd.DataFrame(rec))
                o += n

        for t, idx in keys:
            buf.append((t, idx))
            n_buf += len(idx)
            if n_buf >= CHUNK:
                flush(buf)
                buf, n_buf = [], 0
        if buf:
            flush(buf)
        out = pd.concat(rows, ignore_index=True)
        out.to_csv(output / "forecasts" / f"Y{year}_s{k}_{split}.csv.gz", index=False)
        if split == "test" and not comparison:
            for h in HORIZONS:
                mm = out[f"Class_{h}"].notna()
                yy = out.loc[mm, f"Class_{h}"]
                test_auc[h] = float(roc_auc_score(yy, out.loc[mm, f"Pred_Prob_{h}"])) if yy.nunique() == 2 else None

    meta = {"year": year, "seed_index": k, "seed": seed, "dates": {a: str(b.date()) for a, b in fd.items()},
            "features_sha256": spec["features_sha256"], "features_file_sha256": spec["features_file_sha256"],
            "code_sha256": file_sha(Path(__file__)),
            "n_train": int(len(Xtr)), "n_val": int(len(Xv)), **sample_metadata,
            "train_pos_rate": ytr.mean(0).round(4).tolist(), "n_features": int(len(feat_idx)),
            "dropped_features": [name for i, name in enumerate(FEATURES) if i not in feat_idx],
            "securities_total": len(data),
            "epochs_run": len(va), "best_epoch": best_epoch, "best_val_auc": float(max(va[3:] or va)),
            "test_auc": test_auc, "minutes": round((time.time() - t0) / 60, 2),
            "minutes_split": {"data": round(t_data / 60, 2), "fit": round(t_fit / 60, 2),
                              "forecast": round((time.time() - t0 - t_data - t_fit) / 60, 2)},
            "versions": {"tensorflow": tf.__version__, "numpy": np.__version__, "pandas": pd.__version__}}
    (output / "meta" / f"Y{year}_s{k}.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps({x: meta[x] for x in ["year", "seed_index", "n_train", "best_epoch", "best_val_auc", "test_auc",
                                           "minutes", "minutes_split"]}), flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["prepare", "job", "run"])
    ap.add_argument("--year", type=int)
    ap.add_argument("--comparison", action="store_true", help="use corrected head-to-head samples")
    ap.add_argument("--seed-index", type=int, default=0)
    ap.add_argument("--years", default="2016-2024")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--threads", type=int, default=5)
    a = ap.parse_args()
    if a.comparison and a.mode == "prepare":
        ap.error("comparison consumes the existing frozen features")
    if a.comparison:
        years = [a.year] if a.mode == "job" else wf.parse_years(a.years)
        if not years or any(year not in range(2016, 2025) for year in years):
            ap.error("only the registered 2016–2024 development folds are allowed")
    output = OUT / "model_comparison" / "lstm" if a.comparison else OUT
    for sub in ["forecasts", "meta", "logs"]:
        (output / sub).mkdir(parents=True, exist_ok=True)
    if a.mode == "prepare":
        if (OUT / "feature_spec.json").exists():
            sys.exit("feature_spec.json exists: features are frozen. Delete it only for a deliberate new trial.")
        prepare()
        return
    if a.mode == "job":
        run_job(a.year, a.seed_index, a.threads, comparison=a.comparison)
        return
    _, spec = load_frozen()   # refuse to start on a changed feature list
    del _
    jobs = [(y, k) for y in wf.parse_years(a.years) for k in range(a.seeds)]
    if a.comparison:
        from pit_model_label_dates import experiment_provenance, is_resumable

        provenance = experiment_provenance(spec, Path(__file__))
        jobs = [(y, k) for y, k in jobs if not is_resumable(
            output / "meta" / f"Y{y}_s{k}.json",
            tuple(output / "forecasts" / f"Y{y}_s{k}_{split}.csv.gz" for split in ("val", "test")),
            provenance,
        )]
    else:
        jobs = [(y, k) for y, k in jobs if not (output / "meta" / f"Y{y}_s{k}.json").exists()]
    print(f"[{time.strftime('%H:%M:%S')}] {len(jobs)} jobs, {a.workers} workers x {a.threads} threads", flush=True)
    running, failed = [], []
    while jobs or running:
        while jobs and len(running) < a.workers:
            y, k = jobs.pop(0)
            log = open(output / "logs" / f"Y{y}_s{k}.log", "w")
            cmd = [sys.executable, str(Path(__file__)), "job", "--year", str(y), "--seed-index", str(k),
                   "--threads", str(a.threads)]
            if a.comparison:
                cmd.append("--comparison")
            running.append((subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT), (y, k), log))
        time.sleep(10)
        for item in running[:]:
            p, yk, log = item
            if p.poll() is not None:
                log.close()
                running.remove(item)
                if p.returncode != 0:
                    failed.append(yk)
                print(f"[{time.strftime('%H:%M:%S')}] Y{yk[0]} s{yk[1]} "
                      f"{'ok' if p.returncode == 0 else f'FAILED rc={p.returncode}'}", flush=True)
    print("done; failed:", failed, flush=True)


if __name__ == "__main__":
    main()
