"""Application configuration."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from backend.data.tenant_constants import DEFAULT_TENANT_ID
from backend.data.warehouse_paths import tenant_warehouse_path as _tenant_warehouse_path
from pydantic_settings import BaseSettings, SettingsConfigDict


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SHADOW_", env_file=".env", extra="ignore")

    api_host: str = "127.0.0.1"
    api_port: int = 8742
    data_dir: Path = Field(default_factory=lambda: _repo_root() / ".data")
    database_url: str = ""
    workspace_dir: Path = Field(default_factory=lambda: _repo_root() / "workspace")
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "llama3.2"
    ollama_api_key: str = "ollama"
    debug_agent: bool = False
    llm_tool_confidence: bool = Field(
        default=False,
        description="If True, use LLM structured output for per-tool confidence (RFI). If False, use fast deterministic heuristics.",
    )
    ingestion_provider: Literal["local", "tarka", "auto"] = Field(
        default="local",
        description="local: Polars/DuckDB only. tarka: require Tarka HTTP ingest. auto: try Tarka when tarka_etl_base_url is set, else local.",
    )
    tarka_etl_base_url: str = Field(
        default="",
        description="Base URL for Tarka ETL (POST {base}/ingest multipart).",
    )
    sandbox_mode: Literal["subprocess", "docker", "pyodide"] = Field(
        default="pyodide",
        description="subprocess: AST-validated local Python. docker: isolate in container. pyodide: WASM sandbox via Node.js.",
    )
    sandbox_docker_image: str = Field(
        default="python:3.12-slim",
        description="Image for sandbox_mode=docker (must include Python + deps you need, e.g. a custom image with polars).",
    )
    sandbox_docker_r_image: str = Field(
        default="rocker/r-ver:4.4.0",
        description="Image for R when sandbox_mode=docker.",
    )
    duckdb_threads: int | None = None
    duckdb_memory_limit: str | None = Field(
        default=None,
        description="Optional DuckDB SET memory_limit, e.g. '4GB'",
    )

    @model_validator(mode="after")
    def _ensure_data_dir_and_db_url(self) -> Settings:
        if not os.environ.get("SHADOW_API_PORT") and os.environ.get("FRAUD_COPILOT_API_PORT"):
            try:
                self.api_port = int(os.environ["FRAUD_COPILOT_API_PORT"])
            except ValueError:
                pass
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not (self.database_url or "").strip():
            primary = (self.data_dir / "shadow.db").resolve()
            legacy = (self.data_dir / "fraud_copilot.db").resolve()
            db_path = primary if primary.exists() else (legacy if legacy.exists() else primary)
            self.database_url = f"sqlite:///{db_path}"
        return self

    @property
    def api_base(self) -> str:
        return f"http://{self.api_host}:{self.api_port}"

    @property
    def datasets_storage_dir(self) -> Path:
        p = self.data_dir / "storage" / "datasets"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def duckdb_storage_dir(self) -> Path:
        p = self.data_dir / "storage" / "duckdb"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def tenant_warehouse_db_path(self, tenant_id: str | None = None) -> Path:
        """Per-tenant DuckDB warehouse (isolated from other tenants)."""
        return _tenant_warehouse_path(self.data_dir, tenant_id or DEFAULT_TENANT_ID)

    @property
    def global_warehouse_db_path(self) -> Path:
        """Default-tenant warehouse path (backward compatible with single-tenant installs)."""
        return self.tenant_warehouse_db_path(DEFAULT_TENANT_ID)


settings = Settings()
