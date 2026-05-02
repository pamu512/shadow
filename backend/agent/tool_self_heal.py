"""Shared helpers: strip tracebacks from agent-visible tool output and rank user-id columns."""
from __future__ import annotations

import re
from typing import Iterable

_TRACE_START = re.compile(r"^traceback\s*\(most recent call last\)\s*:\s*$", re.I | re.M)


def strip_traceback_for_agent_ui(text: str, *, max_prefix_lines: int = 12) -> str:
    """Collapse Python tracebacks to a short head so the UI / agent log never shows raw stacks."""
    if not text or "traceback" not in text.lower():
        return text
    m = _TRACE_START.search(text)
    if not m:
        return text
    head = text[: m.start()].strip()
    lines = [ln for ln in head.splitlines() if ln.strip()]
    if not lines:
        first = text.splitlines()[0] if text.splitlines() else "Tool error"
        return f"{first}\n… (traceback omitted for operator console; see sidecar logs.)"
    tail = "\n".join(lines[-max_prefix_lines:])
    return f"{tail}\n… (traceback omitted for operator console; see sidecar logs.)"


def mentions_missing_user_identifier(text: str) -> bool:
    t = text.lower()
    if "user_id is required" in t:
        return True
    if "could not resolve user id column" in t:
        return True
    if "could not resolve a user / account id column" in t:
        return True
    if "field required" in t and "user_id" in t:
        return True
    if "keyerror" in t and "user_id" in t:
        return True
    if 'column "user_id"' in t or "column 'user_id'" in t:
        return True
    if "user_id" in t and "not found" in t and "column" in t:
        return True
    return False


def _norm_col(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


_USER_SUBSTR = (
    "userid",
    "user_id",
    "customerid",
    "accountid",
    "accid",
    "memberid",
    "uid",
    "account",
    "customer",
    "acc_id",
    "acct",
    "player",
    "payer",
)


def rank_user_column_candidates(columns: Iterable[str]) -> list[str]:
    """Prefer obvious account-id columns for self-heal retries (stable order)."""
    names = [str(c) for c in columns if str(c).strip()]
    scored: list[tuple[int, str]] = []
    for c in names:
        n = _norm_col(c)
        score = sum(1 for s in _USER_SUBSTR if s in n)
        if score:
            scored.append((score, c))
    scored.sort(key=lambda x: (-x[0], x[1].lower()))
    out: list[str] = []
    for _, c in scored:
        if c not in out:
            out.append(c)
    for c in names:
        if c not in out:
            out.append(c)
    return out
