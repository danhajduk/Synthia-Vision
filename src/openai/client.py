"""OpenAI image classification client with strict schema validation."""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

try:
    from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError
except ModuleNotFoundError:  # pragma: no cover - depends on runtime environment
    OpenAI = None  # type: ignore[assignment]

    class APIError(Exception):
        pass

    class APITimeoutError(APIError):
        pass

    class APIConnectionError(APIError):
        pass

    class RateLimitError(APIError):
        pass

from src.config import ServiceConfig
from src.errors import ExternalServiceError, ValidationError
from src.models import OpenAIClassification
from src.openai.policy_helpers import (
    render_prompts,
    resolve_allowed_actions,
    resolve_preset,
    resolve_subject_types,
)

LOGGER = logging.getLogger("synthia_vision.ai")


@dataclass(slots=True)
class OpenAIUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    model: str


class OpenAIClient:
    """Executes image classification requests and enforces output parsing."""

    def __init__(self, config: ServiceConfig) -> None:
        if OpenAI is None:
            raise ExternalServiceError(
                "openai package is not installed. Run pip install -r requirements.txt."
            )
        self._config = config
        self._openai_cfg = config.openai
        self._client = OpenAI(
            api_key=self._openai_cfg.api_key,
            timeout=float(self._openai_cfg.timeout_seconds),
        )

    def classify(
        self,
        *,
        snapshot_bytes: bytes,
        camera_name: str,
    ) -> tuple[OpenAIClassification, OpenAIUsage]:
        allowed_actions = resolve_allowed_actions(camera_name, self._config)
        allowed_subject_types = resolve_subject_types(self._config)
        preset = resolve_preset(camera_name, self._config)
        system_prompt, user_prompt = render_prompts(
            preset=preset,
            camera_name=camera_name,
            allowed_actions=allowed_actions,
            allowed_subject_types=allowed_subject_types,
            config=self._config,
        )
        response_format = self._build_response_format(allowed_actions, allowed_subject_types)
        messages = self._build_messages(system_prompt, user_prompt, snapshot_bytes)

        response = self._request_with_retry(messages=messages, response_format=response_format)
        payload_text = self._extract_text_response(response)
        payload_dict = self._parse_json_payload(payload_text)
        classification = OpenAIClassification.from_dict(payload_dict)

        usage = _extract_usage(response)
        cost_usd = _estimate_cost_usd(
            model=self._openai_cfg.model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
        )
        usage_with_cost = OpenAIUsage(
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            cost_usd=cost_usd,
            model=self._openai_cfg.model,
        )
        LOGGER.info(
            "OpenAI classification success camera=%s action=%s subject_type=%s confidence=%.3f prompt_tokens=%s completion_tokens=%s cost_usd=%.6f",
            camera_name,
            classification.action,
            classification.subject_type,
            classification.confidence,
            usage_with_cost.prompt_tokens,
            usage_with_cost.completion_tokens,
            usage_with_cost.cost_usd,
        )
        return classification, usage_with_cost

    def _request_with_retry(
        self,
        *,
        messages: list[dict[str, Any]],
        response_format: dict[str, Any],
    ) -> Any:
        attempts = max(1, int(getattr(self._openai_cfg, "retry_attempts", 3)))
        backoffs = list(getattr(self._openai_cfg, "retry_backoff_seconds", [0.5, 1.0, 2.0]))

        for attempt_idx in range(attempts):
            try:
                return self._client.chat.completions.create(
                    model=self._openai_cfg.model,
                    messages=messages,
                    response_format=response_format,
                    max_tokens=int(self._openai_cfg.max_output_tokens),
                )
            except (APITimeoutError, APIConnectionError, RateLimitError, APIError) as exc:
                if attempt_idx >= attempts - 1:
                    raise ExternalServiceError(f"OpenAI request failed after retries: {exc}") from exc
                backoff_seconds = backoffs[min(attempt_idx, len(backoffs) - 1)] if backoffs else 0.5
                LOGGER.warning(
                    "OpenAI transient error attempt=%s/%s backoff=%ss error=%s",
                    attempt_idx + 1,
                    attempts,
                    backoff_seconds,
                    exc,
                )
                time.sleep(float(backoff_seconds))
            except Exception as exc:  # pragma: no cover - defensive unexpected provider failure
                raise ExternalServiceError(f"OpenAI request failed: {exc}") from exc
        raise ExternalServiceError("OpenAI request failed with unknown error")

    def _build_response_format(
        self,
        allowed_actions: list[str],
        allowed_subject_types: list[str],
    ) -> dict[str, Any]:
        base_schema = dict(self._config.ai.schema or {})
        if base_schema:
            schema_props = dict(base_schema.get("properties", {}))
        else:
            schema_props = {}
        schema_props["action"] = {"type": "string", "enum": allowed_actions}
        schema_props["subject_type"] = {"type": "string", "enum": allowed_subject_types}

        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["action", "subject_type", "confidence", "description"],
            "properties": {
                **schema_props,
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "description": {"type": "string", "minLength": 1, "maxLength": 200},
            },
        }
        return {
            "type": "json_schema",
            "json_schema": {
                "name": self._config.ai.schema_name,
                "strict": True,
                "schema": schema,
            },
        }

    def _build_messages(
        self,
        system_prompt: str,
        user_prompt: str,
        snapshot_bytes: bytes,
    ) -> list[dict[str, Any]]:
        encoded = base64.b64encode(snapshot_bytes).decode("ascii")
        image_data_url = f"data:image/jpeg;base64,{encoded}"
        return [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            },
        ]

    def _extract_text_response(self, response: Any) -> str:
        choices = getattr(response, "choices", None)
        if not choices:
            raise ValidationError("OpenAI response missing choices")
        first_choice = choices[0]
        message = getattr(first_choice, "message", None)
        if message is None:
            raise ValidationError("OpenAI response missing message")
        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise ValidationError("OpenAI response missing text content")
        return content

    def _parse_json_payload(self, payload_text: str) -> dict[str, Any]:
        try:
            decoded = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            raise ValidationError("OpenAI returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise ValidationError("OpenAI JSON payload must be an object")
        return decoded


def _extract_usage(response: Any) -> OpenAIUsage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return OpenAIUsage(
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            cost_usd=0.0,
            model="unknown",
        )
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    total_tokens = int(getattr(usage, "total_tokens", prompt_tokens + completion_tokens) or 0)
    return OpenAIUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cost_usd=0.0,
        model="unknown",
    )


def _estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    # USD per 1M tokens (input, output). Keep explicit and conservative; unknown models return 0.
    pricing_per_million: dict[str, tuple[float, float]] = {
        "gpt-4o-mini": (0.15, 0.60),
        "gpt-4.1-mini": (0.40, 1.60),
        "gpt-4.1-nano": (0.10, 0.40),
    }
    rates = pricing_per_million.get(model)
    if rates is None:
        return 0.0
    input_rate, output_rate = rates
    return (prompt_tokens / 1_000_000.0) * input_rate + (completion_tokens / 1_000_000.0) * output_rate
