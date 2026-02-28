"""Tests for provider abstraction factory helpers."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.ai.providers import create_classification_provider, create_embedding_provider
from src.errors import ExternalServiceError


class AIProvidersTests(unittest.TestCase):
    def test_create_classification_provider_openai(self) -> None:
        config = SimpleNamespace(ai=SimpleNamespace(provider="openai"))
        sentinel = object()
        with patch("src.ai.providers.OpenAIClient", return_value=sentinel):
            provider = create_classification_provider(config)
        self.assertIs(provider, sentinel)

    def test_create_embedding_provider_openai(self) -> None:
        config = SimpleNamespace(ai=SimpleNamespace(provider="openai"))
        sentinel = object()
        with patch("src.ai.providers.OpenAIEmbeddingClient", return_value=sentinel):
            provider = create_embedding_provider(config)
        self.assertIs(provider, sentinel)

    def test_create_provider_rejects_unsupported(self) -> None:
        config = SimpleNamespace(ai=SimpleNamespace(provider="mock"))
        with self.assertRaises(ExternalServiceError):
            create_classification_provider(config)
        with self.assertRaises(ExternalServiceError):
            create_embedding_provider(config)


if __name__ == "__main__":
    unittest.main()
