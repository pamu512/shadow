"""Heuristic + LLM-assisted code review."""
from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from backend.tools.dataset_schema import describe_csv

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


def review_script(
    script: str,
    language: Literal["python", "r"],
    dataset_path: str | None,
    llm: "BaseChatModel | None" = None,
) -> tuple[str, str, str]:
    schema_block = ""
    if dataset_path:
        info = describe_csv(dataset_path)
        if "error" not in info:
            schema_block = "\n".join(
                f"{c['name']}: {c['dtype']}" for c in info.get("columns", [])
            )
    suggested = script
    notes = "No changes (LLM unavailable or error)."
    if llm is not None:
        from langchain_core.messages import HumanMessage, SystemMessage

        sys = (
            "You are a senior fraud analytics engineer. Given a script and optional dataset schema, "
            "return an improved version only (full code). Use Polars best practices for Python, data.table for R."
        )
        human = f"Language: {language}\nSchema:\n{schema_block or 'unknown'}\n\nScript:\n```{language}\n{script}\n```"
        try:
            msg = llm.invoke([SystemMessage(content=sys), HumanMessage(content=human)])
            suggested = getattr(msg, "content", str(msg))
            if isinstance(suggested, list):
                suggested = "".join(str(p) for p in suggested)
            notes = "LLM-suggested optimization."
        except Exception as exc:  # noqa: BLE001
            notes = f"LLM error, returning original: {exc}"
            suggested = script
    else:
        if language == "python" and "polars" not in script and "pl." not in script:
            suggested = "import polars as pl\n\n" + script
            notes = "Prepended Polars import (offline heuristic)."
    return script, str(suggested), notes
