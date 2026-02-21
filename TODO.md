# Synthia Vision – TODO

This roadmap is structured so that each milestone is independently testable.
No step should require the entire pipeline to be complete.

## 1. Foundation
- [x] Add `src/main.py` entrypoint and app lifecycle wiring.
- [x] Add configuration loader (`config.yaml` + env override for secrets).
- [x] Define core models for Frigate events and OpenAI structured output.
- [x] Add logging setup and basic error handling conventions.

# Phase 2 – MQTT + Event Intake

## 2.1 MQTT Client Wrapper
- [x] Implement mqtt_client.py wrapper
  - connect / reconnect handling
  - graceful shutdown
  - last will message
- [x] Publish retained status topic on startup:
  - home/synthiavision/status = "starting"
  - then "enabled" when ready

✅ TEST:
- Start service
- Verify retained status appears in MQTT Explorer
- Restart service and confirm no duplicate behavior

---

## 2.2 Heartbeat
- [x] Publish heartbeat timestamp every 30–60s
  - home/synthiavision/heartbeat_ts

✅ TEST:
- Confirm heartbeat updates without restarting container

---

## 2.3 Subscribe to Frigate Events
- [x] Subscribe to `frigate/events`
- [x] Log raw event_id + camera + type
- [x] Ignore all processing for now

✅ TEST:
- Publish a canned Frigate event to MQTT
- Confirm log output shows receipt

---

# Phase 3 – Policy Engine (Pure Logic First)

## 3.1 Implement policy_engine.py
- [ ] Pure function:
  should_process(event, state, config) -> Decision
- [ ] Handle:
  - process_on == "end"
  - allowed labels
  - enabled cameras
  - doorbell_only_mode
  - confidence threshold
  - cooldown logic
  - duplicate event_id

✅ UNIT TEST:
- Valid end/person event → accepted
- Wrong label → rejected
- Cooldown active → rejected
- Duplicate event_id → rejected

---

## 3.2 Event Router
- [ ] event_router.py
  - Routes accepted events to "processing"
  - Routes rejected events to debug counter/log

✅ TEST:
- Feed sample events manually
- Verify correct routing decision

---

# Phase 4 – Snapshot Manager

## 4.1 Fetch Event Snapshot
- [ ] Implement snapshot_manager.py
  - GET /api/events/{event_id}/snapshot.jpg
  - timeout handling
  - retry with backoff
  - max_bytes limit

✅ TEST:
- Mock httpx and simulate:
  - success
  - timeout
  - retry then success
  - retry then fail

---

## 4.2 Optional Debug Save
- [ ] If debug enabled:
  - Save snapshot to /app/state/snapshots/

✅ TEST:
- Confirm image file is written

---

# Phase 5 – OpenAI Client

## 5.1 Structured Classification
- [ ] openai_client.py
  classify(snapshot_bytes, context) -> (result, usage, cost)

- [ ] Enforce strict JSON schema validation
- [ ] Extract:
  - prompt_tokens
  - completion_tokens
  - cost

✅ UNIT TEST:
- Valid JSON → parsed
- Invalid JSON → rejected safely
- Missing field → rejected

---

## 5.2 Retry Policy
- [ ] Retry transient OpenAI failures
- [ ] Do NOT retry schema validation failures

✅ TEST:
- Simulate retryable exception
- Confirm max attempts respected

---

# Phase 6 – State & Cost Tracking

## 6.1 Atomic State Store
- [ ] load_state()
- [ ] save_state_atomic() (temp + rename)

✅ UNIT TEST:
- Verify atomic write works
- Simulate crash mid-write (optional advanced)

---

## 6.2 Counters & Resets
- [ ] count_total
- [ ] count_today
- [ ] month2day_total
- [ ] daily_total
- [ ] avg_per_event
- [ ] monthly_by_camera

- [ ] Day rollover reset
- [ ] Month rollover reset

✅ UNIT TEST:
- Simulate date change
- Verify correct reset behavior

---

## 6.3 Budget Guard
- [ ] Block OpenAI calls if over monthly limit
- [ ] Publish status = "budget_blocked"
- [ ] Allow recovery if budget increased

✅ TEST:
- Force cost over limit
- Confirm OpenAI not called
- Confirm status updates

---

# Phase 7 – Publishing Results

## 7.1 MQTT Publisher
- [ ] Publish per-camera:
  - action
  - confidence
  - description
  - last_event_id
  - last_event_ts

- [ ] Publish global:
  - cost metrics
  - counters
  - status

✅ TEST:
- Run with mocked OpenAI
- Verify retained topics exist

---

## 7.2 Error Handling Path
- [ ] Publish safe fallback on:
  - OpenAI failure
  - Schema failure
  - Snapshot failure

✅ TEST:
- Simulate each failure type

---

# Phase 8 – Home Assistant MQTT Discovery

## 8.1 Global Entities
- [ ] Status
- [ ] Cost metrics
- [ ] Event counters

✅ TEST:
- HA creates entities once
- Restart service → no duplicates

---

## 8.2 Per-Camera Entities
- [ ] Action
- [ ] Confidence
- [ ] Description
- [ ] Monthly Cost

✅ TEST:
- Enable second camera in config
- Confirm HA auto-creates new entities

---

## 8.3 Command Topics (HA → Service)
- [ ] Enabled switch
- [ ] Doorbell-only mode
- [ ] High precision mode
- [ ] Monthly budget limit
- [ ] Confidence threshold

✅ TEST:
- Toggle in HA
- Confirm service state updates
- Confirm MQTT state reflects change

---

# Phase 9 – Docker & Deployment

## 9.1 Dockerfile
- [ ] Lightweight Python image
- [ ] Non-root user
- [ ] Proper working directory
- [ ] Healthcheck

---

## 9.2 docker-compose.yml
- [ ] Bind mounts:
  - config/
  - state/
  - logs/
- [ ] Environment variables:
  - OPENAI_API_KEY
  - MQTT_PASSWORD
- [ ] Restart policy

✅ TEST:
- docker compose up -d
- Verify status topic appears

---

# Phase 10 – Local Simulation Tools

## 10.1 Sample Event Publisher
- [ ] tools/publish_sample_event.py
  - Publishes canned Frigate event

## 10.2 Offline Pipeline Runner
- [ ] tools/run_pipeline_once.py
  - Uses mock snapshot + mock OpenAI

✅ TEST:
- Full pipeline without Frigate or OpenAI

---

# Phase 11 – Testing Infrastructure

- [ ] Setup pytest
- [ ] Unit tests:
  - policy
  - state
  - cost
  - dedupe
- [ ] Integration tests with mocks:
  - MQTT
  - httpx
  - OpenAI

---

# Phase 12 – Documentation

- [ ] Update README run instructions
- [ ] Document config.yaml structure
- [ ] Document MQTT topics
- [ ] Add troubleshooting section

---

# Guiding Principle

No feature is “done” unless:
- It is testable independently
- It publishes observable state
- It fails safely
- It survives restart
