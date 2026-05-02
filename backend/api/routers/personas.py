"""Public persona registry for the Agent Console."""
from __future__ import annotations

from fastapi import APIRouter

from backend.agent.personas import PERSONA_REGISTRY
from backend.schemas import PersonaListItem

router = APIRouter(prefix="/api/personas", tags=["personas"])


@router.get("", response_model=list[PersonaListItem])
def list_personas() -> list[PersonaListItem]:
    return [
        PersonaListItem(
            id=p.id,
            display_name=p.display_name,
            recommended_tools=p.recommended_tools,
            suggested_queries=p.suggested_queries,
        )
        for p in PERSONA_REGISTRY.values()
    ]
