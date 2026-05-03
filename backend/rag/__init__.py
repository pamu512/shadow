"""Local RAG: chunked text + Ollama embeddings, cosine retrieval."""
from __future__ import annotations

from backend.rag.knowledge_store import ensure_ingested, search_knowledge

__all__ = ["ensure_ingested", "search_knowledge"]
