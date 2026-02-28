"""OpenAI embeddings client used by optional snapshot embedding cache hooks."""

from __future__ import annotations

from dataclasses import dataclass

try:
    from openai import OpenAI
except ModuleNotFoundError:  # pragma: no cover - runtime dependency
    OpenAI = None  # type: ignore[assignment]

from src.config import ServiceConfig
from src.errors import ExternalServiceError


@dataclass(slots=True)
class EmbeddingResult:
    model: str
    vector: list[float]


class OpenAIEmbeddingClient:
    """Small wrapper around OpenAI embeddings API."""

    def __init__(self, config: ServiceConfig) -> None:
        if OpenAI is None:
            raise ExternalServiceError(
                "openai package is not installed. Run pip install -r requirements.txt."
            )
        self._config = config
        self._client = OpenAI(
            api_key=config.openai.api_key,
            timeout=float(config.openai.timeout_seconds),
        )

    def embed_text(self, *, text: str) -> EmbeddingResult:
        content = str(text or "").strip()
        if not content:
            raise ExternalServiceError("embedding text payload is empty")
        model_name = str(self._config.embeddings.model)
        try:
            response = self._client.embeddings.create(
                model=model_name,
                input=content,
            )
        except Exception as exc:  # pragma: no cover - provider/network failure
            raise ExternalServiceError(f"OpenAI embedding request failed: {exc}") from exc
        data = getattr(response, "data", None) or []
        if not data:
            raise ExternalServiceError("OpenAI embedding response had no data")
        first = data[0]
        vector = list(getattr(first, "embedding", []) or [])
        if not vector:
            raise ExternalServiceError("OpenAI embedding response vector was empty")
        return EmbeddingResult(
            model=model_name,
            vector=[float(v) for v in vector],
        )
