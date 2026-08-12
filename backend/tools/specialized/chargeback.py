"""Chargeback Specialist — reason codes, ARN timelines, representment.

Specialized analytics are not wired yet; callers must not treat stub strings as results.
"""
from __future__ import annotations


def reason_code_rollups_stub() -> str:
    raise NotImplementedError(
        "Chargeback reason_code_rollups is not implemented; refuse stub string"
    )


def arn_dedup_timeline_stub() -> str:
    raise NotImplementedError(
        "Chargeback arn_dedup_timeline is not implemented; refuse stub string"
    )
