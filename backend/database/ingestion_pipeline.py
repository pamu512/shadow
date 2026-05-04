"""Pluggable ingestion: local Polars/DuckDB or optional Tarka ETL HTTP service."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Literal

import httpx

from backend.config import settings

_log = logging.getLogger(__name__)

IngestionProviderName = Literal["local", "tarka", "auto"]


class IngestionPipeline(ABC):
    """Copy dataset to durable storage and materialize per-case DuckDB + schema summary."""

    @abstractmethod
    def ingest_csv(
        self,
        case_id: str,
        source_file: Path,
        original_filename: str,
    ) -> tuple[Path, Path, dict[str, Any]]:
        ...


class LocalIngestionPipeline(IngestionPipeline):
    """Default path: Polars/DuckDB in ``IngestionEngine``."""

    def ingest_csv(
        self,
        case_id: str,
        source_file: Path,
        original_filename: str,
    ) -> tuple[Path, Path, dict[str, Any]]:
        from backend.database.ingestion import IngestionEngine

        return IngestionEngine().ingest_csv(case_id, source_file, original_filename)


class TarkaIngestionPipeline(IngestionPipeline):
    """Offload to Tarka ETL when ``SHADOW_TARKA_ETL_BASE_URL`` is set; expects JSON with paths + summary."""

    def __init__(self, base_url: str, *, timeout_sec: float = 120.0) -> None:
        self._base = (base_url or "").rstrip("/")
        self._timeout = timeout_sec

    def ingest_csv(
        self,
        case_id: str,
        source_file: Path,
        original_filename: str,
    ) -> tuple[Path, Path, dict[str, Any]]:
        if not self._base:
            raise RuntimeError("Tarka pipeline configured without base URL")
        url = f"{self._base}/ingest"
        with httpx.Client(timeout=self._timeout) as client:
            with source_file.open("rb") as fh:
                resp = client.post(
                    url,
                    data={"case_id": case_id, "original_filename": original_filename},
                    files={"file": (original_filename, fh, "text/csv")},
                )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("Tarka /ingest returned non-object JSON")
        ds = data.get("dataset_path") or data.get("csv_path")
        duck = data.get("duckdb_path")
        summary = data.get("schema_summary") if isinstance(data.get("schema_summary"), dict) else {}
        if not ds or not duck:
            raise RuntimeError("Tarka /ingest JSON must include dataset_path and duckdb_path")
        return Path(ds), Path(duck), summary


class _AutoIngestionPipeline(IngestionPipeline):
    def ingest_csv(
        self,
        case_id: str,
        source_file: Path,
        original_filename: str,
    ) -> tuple[Path, Path, dict[str, Any]]:
        return ingest_csv_with_fallback(case_id, source_file, original_filename)


def get_ingestion_pipeline() -> IngestionPipeline:
    """Resolve provider from settings (``local`` | ``tarka`` | ``auto``)."""
    mode: IngestionProviderName = settings.ingestion_provider  # type: ignore[attr-defined]
    tarka_url = (settings.tarka_etl_base_url or "").strip()  # type: ignore[attr-defined]
    if mode == "local":
        return LocalIngestionPipeline()
    if mode == "tarka":
        if not tarka_url:
            _log.warning("ingestion_provider=tarka but tarka_etl_base_url empty; falling back to local")
            return LocalIngestionPipeline()
        return TarkaIngestionPipeline(tarka_url)
    return _AutoIngestionPipeline()


def ingest_csv_with_fallback(
    case_id: str,
    source_file: Path,
    original_filename: str,
) -> tuple[Path, Path, dict[str, Any]]:
    """Try Tarka when URL is set (``auto`` / ``tarka``), otherwise local Polars/DuckDB."""
    mode: IngestionProviderName = settings.ingestion_provider  # type: ignore[attr-defined]
    tarka_url = (settings.tarka_etl_base_url or "").strip()  # type: ignore[attr-defined]
    if mode in ("tarka", "auto") and tarka_url:
        try:
            return TarkaIngestionPipeline(tarka_url).ingest_csv(case_id, source_file, original_filename)
        except Exception as exc:  # noqa: BLE001
            _log.warning("Tarka ingest failed (%s); falling back to local Polars/DuckDB", exc)
    return LocalIngestionPipeline().ingest_csv(case_id, source_file, original_filename)
