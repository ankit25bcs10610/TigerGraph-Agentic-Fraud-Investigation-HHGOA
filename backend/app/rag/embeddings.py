"""Configurable embedding providers; retrieval never owns API credentials."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol, Sequence


class EmbeddingConfigurationError(ValueError):
    pass


class EmbeddingProvider(Protocol):
    @property
    def dimension(self) -> int: ...
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class EmbeddingSettings:
    provider: str
    model: str
    api_key: str | None = None

    @classmethod
    def from_environment(cls, environ: dict[str, str] | None = None) -> "EmbeddingSettings":
        values = os.environ if environ is None else environ
        provider, model = values.get("EMBEDDING_PROVIDER", "").strip(), values.get("EMBEDDING_MODEL", "").strip()
        if provider not in {"local", "openai"}:
            raise EmbeddingConfigurationError("EMBEDDING_PROVIDER must be 'local' or 'openai'.")
        if not model:
            raise EmbeddingConfigurationError("EMBEDDING_MODEL is required.")
        api_key = values.get("OPENAI_API_KEY", "").strip() or None
        if provider == "openai" and not api_key:
            raise EmbeddingConfigurationError("OPENAI_API_KEY is required for the openai provider.")
        return cls(provider=provider, model=model, api_key=api_key)


class LocalSentenceTransformerEmbedding:
    def __init__(self, model: str) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise EmbeddingConfigurationError("Install sentence-transformers for EMBEDDING_PROVIDER=local.") from error
        self._model = SentenceTransformer(model)
        self._dimension = int(self._model.get_sentence_embedding_dimension())

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return self._model.encode(list(texts), normalize_embeddings=True).tolist()


class OpenAIEmbedding:
    def __init__(self, model: str, api_key: str) -> None:
        try:
            from openai import OpenAI
        except ImportError as error:
            raise EmbeddingConfigurationError("Install openai for EMBEDDING_PROVIDER=openai.") from error
        self._client, self._model, self._dimension = OpenAI(api_key=api_key), model, None

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            raise EmbeddingConfigurationError("Embed at least one document before reading the embedding dimension.")
        return self._dimension

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        response = self._client.embeddings.create(model=self._model, input=list(texts))
        vectors = [list(item.embedding) for item in response.data]
        if not vectors:
            raise EmbeddingConfigurationError("Embedding provider returned no vectors.")
        dimension = len(vectors[0])
        if any(len(vector) != dimension for vector in vectors):
            raise EmbeddingConfigurationError("Embedding provider returned inconsistent vector dimensions.")
        self._dimension = dimension
        return vectors


def create_embedding_provider(settings: EmbeddingSettings) -> EmbeddingProvider:
    if settings.provider == "local":
        return LocalSentenceTransformerEmbedding(settings.model)
    assert settings.api_key is not None
    return OpenAIEmbedding(settings.model, settings.api_key)
