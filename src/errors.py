"""Shared error types for predictable handling and logging."""

from __future__ import annotations


class SynthiaVisionError(Exception):
    """Base class for expected application-level errors."""


class ConfigError(SynthiaVisionError):
    """Raised when configuration cannot be loaded or validated."""


class ValidationError(SynthiaVisionError):
    """Raised when external payloads fail validation checks."""


class ExternalServiceError(SynthiaVisionError):
    """Raised when dependency calls fail in a controlled way."""
