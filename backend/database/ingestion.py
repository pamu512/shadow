"""DuckDB-backed CSV ingestion into per-case analytical stores."""
from __future__ import annotations

import io
import logging
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

import duckdb
import polars as pl

from backend.config import settings
from backend.database.duckdb_lock import duckdb_lock_path

_log = logging.getLogger(__name__)
LARGE_TABLE_ROWS = 250_000


def read_csv_to_polars(path: Path) -> pl.DataFrame:
    """
    Fault-tolerant CSV read: encoding sniff, Polars first, Pandas fallback for malformed rows.
    """
    raw = path.read_bytes()
    if not raw:
        return pl.DataFrame()
    text: str
    try:
        import chardet

        enc = chardet.detect(raw[:200_000]) or {}
        name = (enc.get("encoding") or "utf-8").lower()
        if name in ("ascii", None):
            name = "utf-8"
        text = raw.decode(name, errors="replace")
    except Exception:  # noqa: BLE001
        text = raw.decode("utf-8", errors="replace")

    buf = io.StringIO(text)
    try:
        return pl.read_csv(buf, infer_schema_length=50_000, try_parse_dates=True)
    except Exception as polars_exc:  # noqa: BLE001
        _log.warning("Polars read_csv failed (%s); trying Pandas fallback", polars_exc)
        try:
            import pandas as pd

            buf.seek(0)
            pdf = pd.read_csv(
                buf,
                on_bad_lines="warn",
                engine="python",
                encoding_errors="replace",
            )
            return pl.from_pandas(pdf)
        except Exception as pd_exc:  # noqa: BLE001
            _log.warning("Pandas CSV fallback failed: %s", pd_exc)
            raise polars_exc from pd_exc


def _configure_duckdb(con: duckdb.DuckDBPyConnection) -> None:
    if settings.duckdb_threads is not None and settings.duckdb_threads > 0:
        con.execute(f"SET threads TO {int(settings.duckdb_threads)}")
    if settings.duckdb_memory_limit:
        lim = settings.duckdb_memory_limit.replace("'", "''")
        con.execute(f"SET memory_limit = '{lim}'")
    try:
        con.execute("SET preserve_insertion_order = false")
    except Exception:  # noqa: BLE001
        pass


def _safe_filename(name: str) -> str:
    base = Path(name).name
    if not re.match(r"^[a-zA-Z0-9._\-]+$", base):
        return "dataset.csv"
    return base


class IngestionEngine:
    """Moves CSVs to durable storage and builds a DuckDB file per case."""

    def __init__(
        self,
        datasets_root: Path | None = None,
        duckdb_root: Path | None = None,
    ) -> None:
        self.datasets_root = datasets_root or settings.datasets_storage_dir
        self.duckdb_root = duckdb_root or settings.duckdb_storage_dir

    def ingest_csv(
        self,
        case_id: str,
        source_file: Path,
        original_filename: str,
    ) -> tuple[Path, Path, dict[str, Any]]:
        """
        Copy CSV into storage, materialize DuckDB table `dataset`, return paths and schema summary.
        """
        self.datasets_root.mkdir(parents=True, exist_ok=True)
        self.duckdb_root.mkdir(parents=True, exist_ok=True)

        case_dir = self.datasets_root / case_id
        case_dir.mkdir(parents=True, exist_ok=True)

        dest_name = _safe_filename(original_filename)
        dest_csv = case_dir / dest_name
        shutil.copy2(source_file, dest_csv)

        duck_path = self.duckdb_root / f"{case_id}.duckdb"
        csv_abs = dest_csv.resolve()

        with duckdb_lock_path(duck_path):
            con = duckdb.connect(str(duck_path))
            try:
                _configure_duckdb(con)
                con.execute("DROP TABLE IF EXISTS dataset")
                df = read_csv_to_polars(csv_abs)
                tmp_csv = case_dir / f"._mat_{uuid.uuid4().hex}.csv"
                try:
                    df.write_csv(tmp_csv)
                    con.execute(
                        "CREATE TABLE dataset AS SELECT * FROM read_csv_auto(?, header=true)",
                        [str(tmp_csv.resolve())],
                    )
                finally:
                    tmp_csv.unlink(missing_ok=True)
                summary = self._schema_summary(con)
            finally:
                con.close()

        return dest_csv, duck_path, summary

    def _schema_summary(self, con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
        describe = con.sql("SELECT column_name, column_type FROM (DESCRIBE dataset)").fetchall()
        row_count = con.sql("SELECT COUNT(*) FROM dataset").fetchone()[0]
        if row_count > LARGE_TABLE_ROWS:
            columns: list[dict[str, Any]] = [
                {
                    "name": col_name,
                    "dtype": col_type,
                    "null_count": None,
                    "row_count": int(row_count),
                }
                for col_name, col_type in describe
            ]
            return {
                "row_count": int(row_count),
                "columns": columns,
                "note": "Per-column null counts skipped for large datasets (avoids O(cols×rows) scans). Query with SQL as needed.",
            }
        columns = []
        for col_name, col_type in describe:
            quoted = f'"{str(col_name).replace(chr(34), chr(34)+chr(34))}"'
            nulls = con.sql(f"SELECT COUNT(*) FROM dataset WHERE {quoted} IS NULL").fetchone()[0]
            columns.append(
                {
                    "name": col_name,
                    "dtype": col_type,
                    "null_count": int(nulls),
                    "row_count": int(row_count),
                }
            )
        return {"row_count": int(row_count), "columns": columns}

    def run_select(self, case_id: str, sql: str) -> tuple[list[str], list[list[Any]]]:
        """Execute a read-only SQL against the case DuckDB (must be SELECT / WITH)."""
        stmt = sql.strip().rstrip(";")
        lowered = stmt.lower()
        if not (lowered.startswith("select") or lowered.startswith("with")):
            raise ValueError("Only SELECT / WITH queries are allowed.")
        forbidden = (" insert ", " update ", " delete ", " attach ", " detach ", " copy ", " export ")
        for bad in forbidden:
            if bad in f" {lowered} ":
                raise ValueError("Mutating operations are not allowed.")

        duck_path = self.duckdb_root / f"{case_id}.duckdb"
        if not duck_path.is_file():
            raise FileNotFoundError("Case analytical database not found; ingest a dataset first.")

        with duckdb_lock_path(duck_path):
            con = duckdb.connect(str(duck_path), read_only=True)
            try:
                try:
                    _configure_duckdb(con)
                except Exception:  # noqa: BLE001
                    pass
                rel = con.sql(stmt)
                cols = [str(c) for c in rel.columns]
                rows = [list(r) for r in rel.fetchall()]
                return cols, rows
            finally:
                con.close()


def new_lead_id() -> str:
    return str(uuid.uuid4())
