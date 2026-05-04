"""Per-DuckDB-file locks: concurrent work on different cases/warehouses; one writer per file."""
from __future__ import annotations

import threading
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

class DuckDBLockManager:
    """One re-entrant lock per resolved database path (case DuckDB or tenant warehouse)."""

    def __init__(self) -> None:
        self._locks: dict[str, threading.RLock] = {}
        self._meta = threading.Lock()

    def _key(self, path: str | Path | None) -> str:
        if path is None:
            return "__none__"
        p = Path(path).expanduser()
        try:
            return str(p.resolve())
        except OSError:
            return str(p)

    def _get(self, key: str) -> threading.RLock:
        with self._meta:
            if key not in self._locks:
                self._locks[key] = threading.RLock()
            return self._locks[key]

    @contextmanager
    def hold_path(self, path: str | Path | None) -> Generator[None, None, None]:
        lk = self._get(self._key(path))
        lk.acquire()
        try:
            yield
        finally:
            lk.release()


_manager = DuckDBLockManager()


@contextmanager
def duckdb_lock_path(path: str | Path | None) -> Generator[None, None, None]:
    """Hold while opening/querying the DuckDB file at ``path`` (resolved path is the lock key)."""
    with _manager.hold_path(path):
        yield


def lock_key_for_path(path: str | Path | None) -> str:
    """Expose normalized lock key (tests / debugging)."""
    return _manager._key(path)
