# Phase 0 Baseline Snapshot

Date: 2026-02-22

## Current Runtime Behavior (Before Sprint Implementation)
- Frigate intake uses MQTT subscription to `frigate/events`.
- Runtime MQTT namespace is derived from `service.mqtt_prefix` (`home/synthiavision` in current config).
- Service lifecycle status publishes retained values including `starting`, `enabled`, `budget_blocked`, `stopped`, and LWT `unavailable`.
- Non-processed events currently publish status-only camera updates:
  - `last_event_id`
  - `last_event_ts`
  - `result_status`
- Camera default/idle topics currently initialize as:
  - `result_status=waiting`
  - `action=waiting`
  - `description=waiting for event`
- Cost/token counters are persisted to `state.json` with atomic writes.

## Current Gaps Relative to Sprint Goals
- No bounded internal queue exists between MQTT intake and processing.
- No degraded status based on queue pressure is implemented yet.
- No SQLite event/metrics/error journal is implemented yet.
- No built-in web UI/auth flows are implemented yet.
- Smart update pHash gating is not implemented yet.

## Phase 0 Constants Introduced
- `EVENT_QUEUE_MAX_SIZE = 50`
- `DEGRADE_HIGH_WATERMARK = 40`
- `DEGRADE_LOW_WATERMARK = 10`
- `DEGRADE_SUSTAIN_SECONDS = 30`

Defined in `src/runtime/constants.py` as the single source for upcoming queue/degraded logic.
