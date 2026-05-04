"""Persistent DuckDB warehouse for cross-case CSV analytics."""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import polars as pl

from backend.config import settings
from backend.data.tenant_constants import DEFAULT_TENANT_ID
from backend.data.warehouse_paths import tenant_warehouse_path
from backend.database.duckdb_lock import duckdb_lock_path
from backend.database.ingestion import _configure_duckdb, read_csv_to_polars
from backend.tools.entity_columns import extract_entities_from_row


def _utc_now() -> datetime:
    """Naive UTC timestamp (DuckDB TIMESTAMP) — avoids optional ``pytz`` for TIMESTAMPTZ."""
    return datetime.now(UTC).replace(tzinfo=None)


class GlobalWarehouse:
    """
    Central DuckDB store: every ingested CSV row is appended with ``source_case_id`` and
    ``upload_timestamp``. ``entity_map`` aggregates distinct cases per entity.
    """

    def __init__(self, db_path: Path | None = None, tenant_id: str | None = None) -> None:
        if db_path is not None:
            self.db_path = Path(db_path)
        else:
            tid = (tenant_id or DEFAULT_TENANT_ID).strip() or DEFAULT_TENANT_ID
            self.db_path = Path(tenant_warehouse_path(settings.data_dir, tid))

    def _connect(self) -> duckdb.DuckDBPyConnection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(self.db_path))
        _configure_duckdb(con)
        return con

    def ensure_schema(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute("""
            CREATE TABLE IF NOT EXISTS warehouse_events (
                source_case_id VARCHAR NOT NULL,
                upload_timestamp TIMESTAMP NOT NULL,
                source_filename VARCHAR,
                row_index BIGINT NOT NULL,
                row_json VARCHAR NOT NULL
            );
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS entity_occurrences (
                source_case_id VARCHAR NOT NULL,
                upload_timestamp TIMESTAMP NOT NULL,
                entity_type VARCHAR NOT NULL,
                entity_value VARCHAR NOT NULL,
                source_column VARCHAR NOT NULL
            );
        """)
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_wh_events_case ON warehouse_events (source_case_id);",
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_entity_occ_type_val ON entity_occurrences (entity_type, entity_value);",
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_entity_occ_case ON entity_occurrences (source_case_id);",
        )

    def rebuild_entity_map(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute("""
            CREATE OR REPLACE TABLE entity_map AS
            SELECT
                entity_type,
                entity_value,
                COUNT(DISTINCT source_case_id)::BIGINT AS distinct_case_count,
                MIN(upload_timestamp) AS first_seen,
                MAX(upload_timestamp) AS last_seen,
                LIST(DISTINCT source_case_id) AS case_ids
            FROM entity_occurrences
            GROUP BY entity_type, entity_value;
        """)

    def append_case_csv(self, case_id: str, csv_path: Path, original_filename: str) -> dict[str, Any]:
        """
        Append all rows from ``csv_path`` into ``warehouse_events`` and refresh ``entity_occurrences``
        / ``entity_map`` for this batch.
        """
        cid = str(case_id).strip()
        if not cid:
            return {"ok": False, "error": "case_id required"}
        try:
            uuid.UUID(cid)
        except ValueError:
            return {"ok": False, "error": "case_id must be a UUID string"}
        path = Path(csv_path)
        if not path.is_file():
            return {"ok": False, "error": f"CSV not found: {path}"}

        upload_ts = _utc_now()
        fname = Path(original_filename).name[:512]

        try:
            df = read_csv_to_polars(path)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"Failed to read CSV: {exc}"}

        if len(df) == 0:
            return {"ok": False, "error": "CSV is empty"}

        n = len(df)
        event_rows: list[tuple[str, Any, str, int, str]] = []
        for idx, row in enumerate(df.to_dicts()):
            event_rows.append(
                (
                    cid,
                    upload_ts,
                    fname,
                    idx,
                    json.dumps(row, default=str, ensure_ascii=False),
                )
            )

        entity_rows: list[tuple[str, Any, str, str, str]] = []
        for row in df.to_dicts():
            for et, val, scol in extract_entities_from_row(row):
                entity_rows.append((cid, upload_ts, et, val, scol))

        with duckdb_lock_path(self.db_path):
            con = self._connect()
            try:
                self.ensure_schema(con)
                ev_chunk = 2000
                for i in range(0, len(event_rows), ev_chunk):
                    part = event_rows[i : i + ev_chunk]
                    con.executemany(
                        """
                        INSERT INTO warehouse_events
                        (source_case_id, upload_timestamp, source_filename, row_index, row_json)
                        VALUES (?, ?, ?, ?, ?);
                        """,
                        part,
                    )
                if entity_rows:
                    chunk = 8000
                    for i in range(0, len(entity_rows), chunk):
                        part = entity_rows[i : i + chunk]
                        con.executemany(
                            """
                            INSERT INTO entity_occurrences
                            (source_case_id, upload_timestamp, entity_type, entity_value, source_column)
                            VALUES (?, ?, ?, ?, ?);
                            """,
                            part,
                        )
                self.rebuild_entity_map(con)
            finally:
                con.close()

        return {
            "ok": True,
            "rows_appended": n,
            "source_case_id": cid,
            "upload_timestamp": upload_ts.isoformat(),
            "entity_extractions": len(entity_rows),
            "warehouse_path": str(self.db_path.resolve()),
        }

    def remove_case(self, case_id: str) -> dict[str, Any]:
        """Drop warehouse rows for ``case_id`` and rebuild ``entity_map`` (no-op if DB missing)."""
        cid = str(case_id).strip()
        if not cid:
            return {"ok": False, "error": "case_id required"}
        if not self.db_path.is_file():
            return {"ok": True, "removed": False, "note": "warehouse file not present"}
        with duckdb_lock_path(self.db_path):
            con = self._connect()
            try:
                self.ensure_schema(con)
                con.execute("DELETE FROM warehouse_events WHERE source_case_id = ?", [cid])
                con.execute("DELETE FROM entity_occurrences WHERE source_case_id = ?", [cid])
                self.rebuild_entity_map(con)
            finally:
                con.close()
        return {"ok": True, "removed": True, "source_case_id": cid}
