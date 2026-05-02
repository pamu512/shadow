"""Multi-agent registry: distinct agents with tool gates and reasoning protocols."""

from backend.agents.registry import (
    DEFAULT_AGENT_ID,
    FRAUD_AGENT_REGISTRY,
    FraudAgent,
    get_fraud_agent,
    list_fraud_agent_ids,
)

__all__ = [
    "DEFAULT_AGENT_ID",
    "FRAUD_AGENT_REGISTRY",
    "FraudAgent",
    "get_fraud_agent",
    "list_fraud_agent_ids",
]
