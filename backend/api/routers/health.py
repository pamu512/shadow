"""Health router."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.api.ollama_health import fetch_ollama_model_names, ollama_reachable
from backend.llm_preferences import (
    effective_ollama_model,
    env_default_ollama_model,
    read_ollama_model_override,
    set_ollama_model_override,
    validate_ollama_model_name,
)
from backend.schemas import HealthResponse, LlmPreferencesOut, LlmPreferencesPatch, OllamaModelsOut

router = APIRouter(tags=["health"])


def _llm_preferences_out() -> LlmPreferencesOut:
    eff = effective_ollama_model()
    ov = read_ollama_model_override()
    return LlmPreferencesOut(
        ollama_model=eff,
        env_default=env_default_ollama_model(),
        using_override=ov is not None,
    )


def _apply_llm_preferences_patch(body: LlmPreferencesPatch) -> LlmPreferencesOut:
    if body.ollama_model is None:
        set_ollama_model_override(None)
    else:
        try:
            validate_ollama_model_name(body.ollama_model)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        set_ollama_model_override(body.ollama_model)
    return _llm_preferences_out()


@router.get("/ollama-models", response_model=OllamaModelsOut)
async def list_ollama_models() -> OllamaModelsOut:
    """Local tags from Ollama (same host as ``SHADOW_OLLAMA_BASE_URL``); powers the model picker."""
    models, err = await fetch_ollama_model_names()
    return OllamaModelsOut(models=models, error=err)


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    ok_ollama = await ollama_reachable()
    ov = read_ollama_model_override()
    return HealthResponse(
        ok=True,
        ollama_reachable=ok_ollama,
        ollama_model=effective_ollama_model(),
        ollama_env_default=env_default_ollama_model(),
        ollama_using_override=ov is not None,
    )


@router.get("/llm-preferences", response_model=LlmPreferencesOut)
async def get_llm_preferences() -> LlmPreferencesOut:
    return _llm_preferences_out()


@router.get("/api/preferences/llm", response_model=LlmPreferencesOut)
async def get_llm_preferences_legacy_path() -> LlmPreferencesOut:
    """Alias for older UI bundles / bookmarks."""
    return _llm_preferences_out()


@router.patch("/llm-preferences", response_model=LlmPreferencesOut)
async def patch_llm_preferences(body: LlmPreferencesPatch) -> LlmPreferencesOut:
    return _apply_llm_preferences_patch(body)


@router.patch("/api/preferences/llm", response_model=LlmPreferencesOut)
async def patch_llm_preferences_legacy_path(body: LlmPreferencesPatch) -> LlmPreferencesOut:
    return _apply_llm_preferences_patch(body)
