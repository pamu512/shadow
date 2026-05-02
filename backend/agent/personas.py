"""Persona definitions derived from the multi-agent FraudAgent registry."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from backend.agents.registry import (
    DEFAULT_AGENT_ID,
    FRAUD_AGENT_REGISTRY,
    FraudAgent,
    get_fraud_agent,
    list_fraud_agent_ids,
)


@dataclass(frozen=True)
class Persona:
    """Definition for one investigative lens (UI + prompts)."""

    id: str
    display_name: str
    system_prompt: str
    recommended_tools: list[str]
    suggested_queries: list[str]


DEFAULT_PERSONA_ID: Final[str] = DEFAULT_AGENT_ID


def _persona_from_agent(fa: FraudAgent) -> Persona:
    return Persona(
        id=fa.id,
        display_name=fa.display_name,
        system_prompt=fa.system_prompt + fa.analyst_prompt_suffix(),
        recommended_tools=list(fa.recommended_tools),
        suggested_queries=list(fa.suggested_queries),
    )


PERSONA_REGISTRY: dict[str, Persona] = {k: _persona_from_agent(v) for k, v in FRAUD_AGENT_REGISTRY.items()}


def get_persona(persona_id: str | None) -> Persona:
    """Resolve a persona id to its definition, falling back to the default analyst."""
    return _persona_from_agent(get_fraud_agent(persona_id))


def list_persona_ids() -> list[str]:
    return list_fraud_agent_ids()
