"""Run heavy ML fits in child processes so the FastAPI / LangGraph thread is not CPU-starved."""
from __future__ import annotations

import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any

# Spawn avoids fork-related issues with threads (uvicorn) on macOS.
_mp_ctx = multiprocessing.get_context("spawn")
_executor: ProcessPoolExecutor | None = None


def _executor() -> ProcessPoolExecutor:
    global _executor
    if _executor is None:
        workers = max(1, min(4, int(os.environ.get("SHADOW_ML_POOL_WORKERS", "2"))))
        _executor = ProcessPoolExecutor(max_workers=workers, mp_context=_mp_ctx)
    return _executor


def isolation_forest_worker(payload: tuple[str, float]) -> dict[str, Any]:
    path, contamination = payload
    from backend.tools.fraud_ml_pipelines import run_isolation_forest_scan

    return run_isolation_forest_scan(path, contamination=contamination)


def xgboost_worker(payload: tuple[str, str]) -> dict[str, Any]:
    path, target_column = payload
    from backend.tools.fraud_ml_pipelines import run_xgboost_fraud_fit

    return run_xgboost_fraud_fit(path, target_column)


def run_isolation_forest_in_process(
    path: str,
    contamination: float,
    *,
    timeout_sec: int = 300,
) -> dict[str, Any]:
    fut = _executor().submit(isolation_forest_worker, (path, contamination))
    try:
        return fut.result(timeout=timeout_sec)
    except FuturesTimeout:
        fut.cancel()
        return {"ok": False, "error": f"Isolation forest scan timed out after {timeout_sec}s."}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"ML worker failed: {exc!s}"}


def run_xgboost_in_process(
    path: str,
    target_column: str,
    *,
    timeout_sec: int = 600,
) -> dict[str, Any]:
    fut = _executor().submit(xgboost_worker, (path, target_column))
    try:
        return fut.result(timeout=timeout_sec)
    except FuturesTimeout:
        fut.cancel()
        return {"ok": False, "error": f"XGBoost fit timed out after {timeout_sec}s."}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"ML worker failed: {exc!s}"}
