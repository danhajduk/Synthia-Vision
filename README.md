# Synthia Vision

Synthia Vision is a standalone, event-aware AI service for Frigate + OpenAI + MQTT + Home Assistant.

Current status: Foundation is implemented (service entrypoint, config system, core models, logging/error conventions). MQTT/event processing is the next phase.

## Implemented So Far

### Foundation
- Async service runtime with graceful shutdown on `SIGINT`/`SIGTERM` (`src/main.py`)
- Centralized logging setup (`src/logging_utils.py`)
- Shared application error types (`src/errors.py`)
- Core validated models for:
  - Frigate event payloads
  - OpenAI structured classification output (`src/models.py`)
- YAML-based config loader with:
  - New schema support from `config/config.yaml`
  - `${ENV_VAR}` placeholder resolution
  - Type validation and guardrails (`src/config/settings.py`)

## Project Layout

- `src/main.py`: service lifecycle entrypoint
- `src/config/settings.py`: config dataclasses + loader/validation
- `src/models.py`: Frigate/OpenAI payload models
- `src/logging_utils.py`: logging conventions
- `src/errors.py`: app-specific exceptions
- `config/config.yaml`: main runtime configuration
- `TODO.md`: implementation tracker

## Configuration

Primary config file:
- `config/config.yaml`

Secrets can be provided either in YAML placeholders or via environment variables:
- `OPENAI_API_KEY`
- `MQTT_PASSWORD`
- `MQTT_USERNAME`
- `MQTT_HOST`
- `FRIGATE_BASE_URL`
- `OPENAI_MODEL`
- `SYNTHIA_LOG_LEVEL`
- `SYNTHIA_MONTHLY_BUDGET_LIMIT`
- `SYNTHIA_CONFIDENCE_THRESHOLD`

You can also override config file path with:
- `SYNTHIA_CONFIG`

## Local Run (Current)

1. Install dependencies:
```bash
pip install -r requirements.txt
```
2. Set required secrets (minimum):
```bash
export OPENAI_API_KEY="your-key"
```
3. Start service:
```bash
python -m src.main
```

## Roadmap

Next major section is MQTT integration:
- connect/reconnect
- subscribe to `frigate/events`
- publish retained state/status topics
