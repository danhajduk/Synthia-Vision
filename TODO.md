# Synthia Vision TODO

## 1. Foundation
- [x] Add `src/main.py` entrypoint and app lifecycle wiring.
- [x] Add configuration loader (`config.yaml` + env override for secrets).
- [x] Define core models for Frigate events and OpenAI structured output.
- [x] Add logging setup and basic error handling conventions.

## 2. MQTT Integration
- [ ] Implement MQTT client connect/reconnect logic.
- [ ] Subscribe to `frigate/events`.
- [ ] Publish retained topics under `home/synthiavision/...`.
- [ ] Add status heartbeat topic: `home/synthiavision/status`.

## 3. Policy + Routing
- [ ] Implement event validation and schema checks.
- [ ] Add MVP policy filters (`type=end`, `label=person`).
- [ ] Add per-camera enable/disable support.
- [ ] Add dedupe and cooldown suppression by camera/event.

## 4. Snapshot + OpenAI
- [ ] Implement Frigate snapshot fetch by event ID.
- [ ] Add OpenAI client with strict JSON response parsing.
- [ ] Validate required fields: `action`, `confidence`, `description`.
- [ ] Handle retries/timeouts for transient failures.

## 5. State + Cost Tracking
- [ ] Implement atomic `state/state.json` read/write.
- [ ] Track event counters (`count_total`, `count_today`).
- [ ] Track cost metrics (`last`, `daily_total`, `month2day_total`, `avg_per_event`).
- [ ] Track monthly camera totals.
- [ ] Enforce monthly budget cap before OpenAI calls.
- [ ] Add reset logic for day/month boundaries.

## 6. Home Assistant Discovery
- [ ] Publish MQTT Discovery entities for key sensors and controls.
- [ ] Include cost metrics, event counters, and service status entities.
- [ ] Ensure all state topics are retained.

## 7. Packaging + Deployment
- [ ] Add `requirements.txt`.
- [ ] Add Dockerfile and `docker-compose.yml`.
- [ ] Mount `config/` and `state/` volumes.
- [ ] Add health endpoint/readiness check.

## 8. Testing
- [ ] Unit tests for policy engine.
- [ ] Unit tests for atomic state writes.
- [ ] Unit tests for cost calculations and budget guard.
- [ ] Unit tests for dedupe/cooldown behavior.
- [ ] Integration test with mocked MQTT, Frigate, and OpenAI.

## 9. Documentation
- [ ] Update README with setup/run instructions.
- [ ] Document MQTT topics and payload examples.
- [ ] Document config keys and environment variables.
- [ ] Add troubleshooting and operational notes.
