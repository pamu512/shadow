"""Ollama via OpenAI-compatible client."""
from __future__ import annotations

from langchain_openai import ChatOpenAI

from backend.config import settings
from backend.llm_preferences import effective_ollama_model


def get_llm(**kwargs):
    return ChatOpenAI(
        base_url=settings.ollama_base_url,
        api_key=settings.ollama_api_key,
        model=effective_ollama_model(),
        temperature=0.2,
        **kwargs,
    )
