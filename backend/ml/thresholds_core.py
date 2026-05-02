"""Reproducible sklearn threshold optimization helpers."""
from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np
import polars as pl
from sklearn.metrics import roc_curve


def hash_dataset_sample(df: pl.DataFrame, feature_cols: list[str]) -> str:
    h = hashlib.sha256()
    schema = json.dumps([(c, str(df[c].dtype)) for c in feature_cols], sort_keys=True).encode()
    h.update(schema)
    n = len(df)
    if n == 0:
        return h.hexdigest()
    head = df.select(feature_cols).head(3).to_numpy().tobytes()
    tail = df.select(feature_cols).tail(3).to_numpy().tobytes()
    h.update(head)
    h.update(tail)
    h.update(str(n).encode())
    return h.hexdigest()


def select_feature_columns(df: pl.DataFrame, exclude: set[str]) -> list[str]:
    cols = []
    for c in df.columns:
        if c in exclude:
            continue
        if df[c].dtype in (pl.Float32, pl.Float64, pl.Int32, pl.Int64, pl.UInt32, pl.UInt64):
            cols.append(c)
    return cols


def youden_j_threshold(y_true: np.ndarray, scores: np.ndarray) -> tuple[float, dict[str, float]]:
    fpr, tpr, thresholds = roc_curve(y_true, scores)
    if len(thresholds) == 0:
        return 0.5, {"tpr": 0.0, "fpr": 0.0}
    j = tpr[:-1] - fpr[:-1]
    idx = int(np.argmax(j))
    thr = float(thresholds[idx])
    return thr, {"tpr": float(tpr[idx]), "fpr": float(fpr[idx])}


def min_fpr_at_min_recall(y_true: np.ndarray, scores: np.ndarray, min_recall: float = 0.8) -> tuple[float, dict[str, float]]:
    fpr, tpr, thresholds = roc_curve(y_true, scores)
    mask = tpr[:-1] >= min_recall
    if not np.any(mask):
        return youden_j_threshold(y_true, scores)
    idxs = np.where(mask)[0]
    best = idxs[np.argmin(fpr[:-1][mask])]
    thr = float(thresholds[best])
    return thr, {"tpr": float(tpr[best]), "fpr": float(fpr[best])}
