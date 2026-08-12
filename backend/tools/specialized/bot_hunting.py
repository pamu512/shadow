"""Bot Hunter — TLS/JA3, interaction entropy, headless signals.

Specialized analytics are not wired yet; callers must not treat stub strings as results.
"""
from __future__ import annotations


def tls_fingerprint_clustering_stub() -> str:
    raise NotImplementedError(
        "Bot hunting tls_fingerprint_clustering is not implemented; refuse stub string"
    )


def interaction_entropy_stub() -> str:
    raise NotImplementedError(
        "Bot hunting interaction_entropy is not implemented; refuse stub string"
    )
