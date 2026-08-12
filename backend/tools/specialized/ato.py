"""ATO Investigator — sessions, device graphs, velocity.

Specialized analytics are not wired yet; callers must not treat stub strings as results.
"""
from __future__ import annotations


def ip_velocity_stub() -> str:
    raise NotImplementedError(
        "ATO ip_velocity is not implemented; refuse stub string as analytic output"
    )


def device_fingerprint_graph_stub() -> str:
    raise NotImplementedError(
        "ATO device_fingerprint_graph is not implemented; refuse stub string as analytic output"
    )
