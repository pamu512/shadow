"""Train a lightweight RandomForest and export ONNX for tool output confidence scoring.

Run from repo root: ``python -m backend.agent.train_confidence_model``
Writes ``<repo>/.data/tool_confidence.onnx`` (dummy heuristic-style features).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import FloatTensorType


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    out = repo_root / ".data" / "tool_confidence.onnx"
    rng = np.random.default_rng(42)
    n = 800
    # Features: ok, row_norm, truncated, global_hits, severity — same scale as runtime encoder
    X = rng.random((n, 5)).astype(np.float32)
    score = (
        X[:, 0] * 0.3 + X[:, 1] * 0.2 + X[:, 2] * 0.1 + X[:, 3] * 0.15 + X[:, 4] * 0.25
    )
    y = (score > 0.45).astype(np.int64)
    clf = RandomForestClassifier(n_estimators=40, max_depth=8, random_state=42)
    clf.fit(X, y)
    onx = convert_sklearn(
        clf,
        initial_types=[("input", FloatTensorType([None, 5]))],
        options={id(clf): {"zipmap": False}},
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(onx.SerializeToString())
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
