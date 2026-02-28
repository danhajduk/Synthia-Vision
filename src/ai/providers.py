"""Provider abstraction layer for AI classification and embeddings."""

from __future__ import annotations

from typing import Protocol

from src.config import ServiceConfig
from src.errors import ExternalServiceError
from src.models import OpenAIClassification
from src.openai import (
    EmbeddingResult,
    OpenAIClient,
    OpenAIEmbeddingClient,
    OpenAIUsage,
)


class ClassificationProvider(Protocol):
    # TODO(provider): add non-OpenAI provider implementations behind this interface.
    def classify(
        self,
        *,
        snapshot_bytes: bytes,
        camera_name: str,
        bbox: tuple[int, int, int, int] | None = None,
        force_low_budget: bool = False,
        explain: bool = False,
    ) -> tuple[OpenAIClassification, OpenAIUsage]:
        ...


class EmbeddingProvider(Protocol):
    # TODO(provider): add non-OpenAI embeddings implementations behind this interface.
    def embed_text(self, *, text: str) -> EmbeddingResult:
        ...


def create_classification_provider(config: ServiceConfig) -> ClassificationProvider:
    provider = str(config.ai.provider or "openai").strip().lower()
    if provider != "openai":
        raise ExternalServiceError(
            f"Unsupported ai.provider '{provider}'. OpenAI is the only active provider."
        )
    return OpenAIClient(config)


def create_embedding_provider(config: ServiceConfig) -> EmbeddingProvider:
    provider = str(config.ai.provider or "openai").strip().lower()
    if provider != "openai":
        raise ExternalServiceError(
            f"Unsupported ai.provider '{provider}'. OpenAI is the only active provider."
        )
    return OpenAIEmbeddingClient(config)
