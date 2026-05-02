"""Threshold optimization with reproducibility manifest."""
from __future__ import annotations

import os
import random
from typing import Any, Literal

import numpy as np
import polars as pl
import sklearn
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold

from backend.ml.thresholds_core import (
    hash_dataset_sample,
    min_fpr_at_min_recall,
    select_feature_columns,
    youden_j_threshold,
)

SEED = 42


def _set_seeds(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)


def run_optimize(
    dataset_path: str,
    model_kind: Literal["isolation_forest", "random_forest"],
    target_column: str | None,
    optimization_objective: str | None = None,
) -> dict[str, Any]:
    _set_seeds(SEED)
    df = pl.read_csv(dataset_path, try_parse_dates=True)
    n_rows = len(df)
    target_obj = optimization_objective or "youden_j"

    manifest: dict[str, Any] = {
        "sklearn_version": sklearn.__version__,
        "polars_version": pl.__version__,
        "n_rows": n_rows,
        "seed": SEED,
        "model_kind": model_kind,
        "dataset_path": dataset_path,
        "hash_dataset_sample": None,
        "hyperparams": {},
        "cv_summary": None,
    }

    exclude = set()
    if target_column:
        exclude.add(target_column)
    feature_cols = select_feature_columns(df, exclude)
    if not feature_cols:
        raise ValueError("No numeric feature columns found for modeling.")
    manifest["feature_columns"] = feature_cols
    manifest["hash_dataset_sample"] = hash_dataset_sample(df, feature_cols)

    X = df.select(feature_cols).to_numpy()
    X = np.nan_to_num(X, nan=0.0)

    use_supervised = (
        model_kind == "random_forest"
        and target_column is not None
        and target_column in df.columns
    )

    if not use_supervised:
        contamination_grid = [0.001, 0.01, 0.05]
        candidates: list[tuple[float, float, float]] = []  # contam, mean_thr, stability
        for contam in contamination_grid:
            fold_thresholds: list[float] = []
            skf = StratifiedKFold(n_splits=3, shuffle=True, random_state=SEED)
            pseudo_y = (X[:, 0] > np.median(X[:, 0])).astype(int)
            fold_score_stds: list[float] = []
            for train_idx, val_idx in skf.split(X, pseudo_y):
                clf = IsolationForest(n_estimators=256, contamination=contam, random_state=SEED)
                clf.fit(X[train_idx])
                val_scores = clf.decision_function(X[val_idx])
                thr_q = float(np.quantile(val_scores, contam))
                fold_thresholds.append(thr_q)
                fold_score_stds.append(float(np.std(val_scores)))
            mean_thr = float(np.mean(fold_thresholds))
            stability = float(np.mean(fold_score_stds))
            candidates.append((contam, mean_thr, stability))
        best = min(candidates, key=lambda c: c[2])
        chosen_contam, chosen_thr, stability_mean = best
        final_clf = IsolationForest(
            n_estimators=256,
            contamination=chosen_contam or 0.01,
            random_state=SEED,
        )
        final_clf.fit(X)
        scores = final_clf.decision_function(X)
        manifest["hyperparams"] = {
            "n_estimators": 256,
            "contamination": chosen_contam,
            "threshold_quantile": chosen_contam,
        }
        manifest["cv_summary"] = {
            "fold_score_std_mean": stability_mean,
            "candidates_evaluated": [{"contam": c[0], "thr": c[1], "stab": c[2]} for c in candidates],
        }
        manifest["selected_threshold"] = chosen_thr
        manifest["optimization_objective"] = "isolation_score_quantile_cv"
        thresholds_out = {
            "anomaly_score_threshold": float(chosen_thr or 0.0),
            "rule": "decision_function <= threshold => anomaly (lower is more anomalous)",
        }
        metrics_at = {
            "mean_anomaly_score": float(np.mean(scores)),
            "std_anomaly_score": float(np.std(scores)),
        }
        return {
            "thresholds": thresholds_out,
            "optimization_manifest": manifest,
            "metrics_at_threshold": metrics_at,
            "optimization_objective": manifest["optimization_objective"],
        }

    y = df[target_column].to_numpy()  # type: ignore[arg-type]
    if len(np.unique(y)) < 2:
        raise ValueError("Target column must have at least two classes.")

    clf = RandomForestClassifier(
        n_estimators=300,
        max_depth=None,
        random_state=SEED,
        class_weight="balanced_subsample",
    )
    clf.fit(X, y)
    scores = clf.predict_proba(X)[:, 1]
    manifest["hyperparams"] = {"n_estimators": 300, "class_weight": "balanced_subsample"}
    ap = float(average_precision_score(y, scores))
    roc = float(roc_auc_score(y, scores))
    if target_obj.startswith("min_fpr_at_recall"):
        thr, extras = min_fpr_at_min_recall(y, scores, min_recall=0.8)
    else:
        thr, extras = youden_j_threshold(y, scores)
    pred = (scores >= thr).astype(int)
    tp = float(np.sum((pred == 1) & (y == 1)))
    fp = float(np.sum((pred == 1) & (y == 0)))
    tn = float(np.sum((pred == 0) & (y == 0)))
    fn = float(np.sum((pred == 0) & (y == 1)))
    recall = tp / (tp + fn + 1e-9)
    fpr = fp / (fp + tn + 1e-9)
    manifest["selected_threshold"] = thr
    manifest["cv_summary"] = {"in_sample": True, "pr_auc": ap, "roc_auc": roc}
    thresholds_out = {"score_threshold": thr, "score_definition": "predict_proba positive class"}
    metrics_at = {
        "recall": recall,
        "fpr": fpr,
        "pr_auc": ap,
        "roc_auc": roc,
        **extras,
    }
    manifest["optimization_objective"] = target_obj
    return {
        "thresholds": thresholds_out,
        "optimization_manifest": manifest,
        "metrics_at_threshold": metrics_at,
        "optimization_objective": target_obj,
    }
