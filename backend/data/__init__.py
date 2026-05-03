"""Shared analytical data layer (e.g. cross-case DuckDB warehouse).

Imports are lazy to avoid circular imports with ``backend.config`` during startup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = ["GlobalWarehouse"]

if TYPE_CHECKING:
    from backend.data.warehouse import GlobalWarehouse as GlobalWarehouseType


def __getattr__(name: str) -> Any:
    if name == "GlobalWarehouse":
        from backend.data.warehouse import GlobalWarehouse

        return GlobalWarehouse
    raise AttributeError(name)
