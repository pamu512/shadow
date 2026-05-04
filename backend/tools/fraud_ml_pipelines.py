"""Production-style local ML: Isolation Forest (unsupervised) + gradient boosting (supervised)."""
from __future__ import annotations

import os
import random
from typing import Any

import numpy as np
import polars as pl
from sklearn.ensemble import HistGradientBoostingClassifier, IsolationForest
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import train_test_split

from backend.ml.thresholds_core import select_feature_columns

SEED = 42


def _set_seeds() -> None:
    random.seed(SEED)
    np.random.seed(SEED)
    os.environ["PYTHONHASHSEED"] = str(SEED)


def _downsample_if_needed(df: pl.DataFrame, max_rows: int = 100_000) -> pl.DataFrame:
    """Prevent OOM by downsampling large datasets before converting to NumPy."""
    if len(df) > max_rows:
        return df.sample(n=max_rows, seed=SEED)
    return df


def run_isolation_forest_scan(
    dataset_path: str,
    *,
    contamination: float = 0.02,
    n_estimators: int = 200,
) -> dict[str, Any]:
    """Fit IsolationForest on numeric features; return scores + top anomalous row indices."""
    _set_seeds()
    df = pl.read_csv(dataset_path, try_parse_dates=True)
    original_rows = len(df)
    df = _downsample_if_needed(df)
    
    if len(df) < 10:
        return {"ok": False, "error": "Need at least 10 rows for IF scan."}
    feature_cols = select_feature_columns(df, exclude=set())
    if not feature_cols:
        return {"ok": False, "error": "No numeric feature columns."}
    X = np.nan_to_num(df.select(feature_cols).to_numpy(), nan=0.0)
    clf = IsolationForest(
        n_estimators=n_estimators,
        contamination=min(0.5, max(0.001, contamination)),
        random_state=SEED,
    )
    clf.fit(X)
    scores = clf.decision_function(X)
    order = np.argsort(scores)[: min(25, len(scores))]
    top_rows: list[dict[str, Any]] = []
    for i in order:
        row = df[int(i)]
        top_rows.append({"row_index": int(i), "if_score": float(scores[i]), "preview": row.to_dicts()[0]})
    return {
        "ok": True,
        "model": "isolation_forest",
        "n_rows": original_rows,
        "sampled_rows": len(df),
        "feature_columns": feature_cols,
        "contamination": contamination,
        "summary": "Lower decision_function = more anomalous in feature space (bot-like / rare combinations).",
        "top_anomalies": top_rows,
    }


def run_xgboost_fraud_fit(
    dataset_path: str,
    target_column: str,
    *,
    test_size: float = 0.25,
) -> dict[str, Any]:
    """Supervised fraud / label column with XGBoost if available, else HistGradientBoostingClassifier."""
    _set_seeds()
    df = pl.read_csv(dataset_path, try_parse_dates=True)
    original_rows = len(df)
    df = _downsample_if_needed(df)
    
    tc = (target_column or "").strip()
    if not tc or tc not in df.columns:
        return {"ok": False, "error": f"target_column {tc!r} not in CSV."}
    exclude = {tc}
    feature_cols = select_feature_columns(df, exclude)
    if not feature_cols:
        return {"ok": False, "error": "No numeric feature columns besides target."}
    X = np.nan_to_num(df.select(feature_cols).to_numpy(), nan=0.0)
    y_raw = df[tc].to_numpy().ravel()
    y = np.zeros(len(y_raw), dtype=np.int32)
    for i, v in enumerate(y_raw):
        try:
            fv = float(v)
            y[i] = 1 if fv >= 0.5 or str(v).strip().lower() in ("1", "true", "fraud", "yes") else 0
        except (TypeError, ValueError):
            s = str(v).strip().lower()
            y[i] = 1 if s in ("1", "true", "fraud", "yes") else 0
    if y.sum() < 2 or (1 - y).sum() < 2:
        return {"ok": False, "error": "Need at least 2 positives and 2 negatives for supervised fit."}
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=test_size, random_state=SEED, stratify=y)
    backend = "hist_gradient_boosting"
    try:
        import xgboost as xgb  # noqa: WPS433

        clf = xgb.XGBClassifier(
            n_estimators=120,
            max_depth=5,
            learning_rate=0.08,
            subsample=0.9,
            colsample_bytree=0.85,
            random_state=SEED,
            eval_metric="logloss",
        )
        clf.fit(X_train, y_train)
        backend = "xgboost"
    except Exception:
        clf = HistGradientBoostingClassifier(
            max_depth=6,
            learning_rate=0.06,
            max_iter=180,
            random_state=SEED,
        )
        clf.fit(X_train, y_train)
    p = clf.predict_proba(X_test)[:, 1]
    ap = float(average_precision_score(y_test, p))
    try:
        auc = float(roc_auc_score(y_test, p))
    except ValueError:
        auc = float("nan")
    imp: list[dict[str, Any]] = []
    if hasattr(clf, "feature_importances_"):
        for name, val in sorted(
            zip(feature_cols, clf.feature_importances_, strict=True),
            key=lambda x: -float(x[1]),
        )[:15]:
            imp.append({"feature": name, "importance": float(val)})
    return {
        "ok": True,
        "backend": backend,
        "target_column": tc,
        "n_rows": original_rows,
        "sampled_rows": len(df),
        "feature_columns": feature_cols,
        "test_rows": int(len(y_test)),
        "average_precision": round(ap, 4),
        "roc_auc": round(auc, 4) if auc == auc else None,
        "top_feature_importances": imp,
        "notes": "Train on labeled fraud column; validate with held-out AP/AUC before policy changes.",
    }
