# Synthia Vision – TODO (Next Sprint)

Sprint theme: **Boring runtime + local explain UI** with minimal MQTT clutter.

Execution rule:
- Complete one phase at a time.
- When asked to continue, commit the previous phase and update docs before starting the next.

## Phase 0 – Guardrails & Baseline
- [ ] Snapshot current behavior and document known MQTT/runtime behavior.
- [ ] Define constants for queue/degraded thresholds (`queue_max=50`, degrade high-water and recovery).
- [ ] Add/confirm test harness for new pipeline modules.

Acceptance:
- [ ] Baseline tests run.
- [ ] New sprint constants/config entries are defined in one place.

---

## Phase 1 – Config Refactor (Root + Includes)
- [ ] Add root config model fields: `schema_version`, `includes`, `service.paths.db_file`.
- [ ] Implement include-based loader:
  - [ ] `config.yaml` as root.
  - [ ] `config.d/*.yaml` merged in order.
  - [ ] Deep-merge dicts; lists are replace semantics.
- [ ] Add schema version validation with clear failure message.
- [ ] Normalize MQTT topic derivation from `service.mqtt_prefix`.
- [ ] Ensure no internal hardcoded `synthia/synthiavision/...` topics remain.

Acceptance:
- [ ] Existing runtime config loads via includes.
- [ ] Schema mismatch fails fast with clear error.
- [ ] Topic normalization verified.

---

## Phase 2 – Disable Cropping (Full-Frame Only)
- [ ] Remove/disable bbox/ROI cropping paths in preprocessing.
- [ ] Keep resize/compress token controls.
- [ ] Ensure `input_image` blocks remain used.
- [ ] Force `crop_to_bbox=false` behavior (or remove option).

Acceptance:
- [ ] No crop path is active.
- [ ] Token guard still works.

---

## Phase 3 – SQLite Foundation + DB Layer
- [ ] Add SQLite DB path default: `/app/state/synthia_vision.db`.
- [ ] Implement DB init with WAL mode and sane busy timeout.
- [ ] Add tables:
  - [ ] `events`
  - [ ] `metrics`
  - [ ] `errors`
  - [ ] `users`
  - [ ] `kv`
  - [ ] `cameras`
- [ ] Add DB access module (`src/db/...`) with robust write helpers.

Acceptance:
- [ ] DB initializes on startup.
- [ ] Table creation is idempotent.

---

## Phase 4 – Camera Discovery + Camera Config in SQLite
- [ ] Remove/ignore `policy.cameras` from YAML as source of truth.
- [ ] Upsert discovered cameras from every Frigate event.
- [ ] Mandatory default for new cameras: `enabled=0`.
- [ ] Track `discovered_first_ts` and `last_seen_ts`.
- [ ] Add per-camera settings columns usage:
  - [ ] `prompt_preset`, `confidence_threshold`, `cooldown_s`
  - [ ] `process_end_events`, `process_update_events`, `updates_per_event`
  - [ ] `vision_detail`, `phash_threshold`

Acceptance:
- [ ] New cameras appear in SQLite automatically.
- [ ] New cameras are disabled by default.

---

## Phase 5 – Queue Worker + Backpressure + Degraded State
- [ ] Introduce bounded intake queue (size 50).
- [ ] Keep MQTT callback lightweight (parse/normalize/enqueue only).
- [ ] Add dedicated worker for processing queue items.
- [ ] Implement drop policy:
  - [ ] Drop `update` events first when full.
  - [ ] If still full, drop oldest event (documented choice).
- [ ] Track drop counters in SQLite and summary API.
- [ ] Implement degraded status transitions:
  - [ ] Degrade when queue > 40 for > 30s.
  - [ ] Recover when queue < 10.
  - [ ] Publish only existing status topic.

Acceptance:
- [ ] Queue never exceeds 50.
- [ ] MQTT thread stays responsive under burst load.
- [ ] Degraded transitions behave as specified.

---

## Phase 6 – Event Journal + Error Journal
- [ ] Write one `events` row for each handled event (accepted or rejected).
- [ ] Write `metrics` row when processing path runs.
- [ ] Record reject reasons and skipped reasons in DB, not MQTT debug topics.
- [ ] Record runtime errors in `errors` with component and short detail.

Acceptance:
- [ ] Explainability data exists in SQLite for recent events.
- [ ] MQTT clutter does not increase.

---

## Phase 7 – Smart Update with Perceptual Hash
- [ ] Implement pHash/dHash helper (`src/pipeline/phash.py` or equivalent).
- [ ] For `update` events:
  - [ ] Fetch full-frame snapshot.
  - [ ] Compute hash and compare against last camera hash.
  - [ ] If distance <= threshold, skip OpenAI and mark status accordingly.
- [ ] Persist hash/distance + skip reason in `metrics`.

Acceptance:
- [ ] Near-identical updates skip OpenAI.
- [ ] End events still run normal classification.

---

## Phase 8 – Auth + First-Run Bootstrap
- [ ] Add session-based auth with roles: `guest`, `admin`.
- [ ] Secure password hashing (bcrypt/argon2).
- [ ] First-run bootstrap:
  - [ ] create first admin via setup route and/or `ADMIN_PASSWORD` env.
- [ ] Restrict guest vs admin routes and APIs.

Acceptance:
- [ ] Guest cannot access admin pages/APIs.
- [ ] First admin creation flow is documented and tested.

---

## Phase 9 – Built-in FastAPI + Jinja UI
- [ ] Add routes/pages:
  - [ ] `/` -> `/ui`
  - [ ] `/ui` guest overview (iframe-safe)
  - [ ] `/ui/login`, `/ui/logout`
  - [ ] `/ui/admin`, `/ui/setup`, `/ui/events`, `/ui/events/{id}`, `/ui/errors`
- [ ] Add template/layout files under `src/ui/templates`.
- [ ] Add static assets under `src/ui/static`.

Acceptance:
- [ ] UI is self-hosted, no external frontend toolchain.
- [ ] Guest overview has no controls or sensitive details.

---

## Phase 10 – Setup & Controls (Admin)
- [ ] Setup page global settings:
  - [ ] monthly budget
  - [ ] confidence threshold
  - [ ] doorbell-only mode
  - [ ] high precision mode
  - [ ] default vision detail
  - [ ] default/update pHash threshold
- [ ] Setup page camera section from discovered cameras table.
- [ ] Allow per-camera edits and enable toggles.
- [ ] Clearly label runtime-only vs persisted changes.
- [ ] Persist settings to SQLite `kv` (and config only if explicitly supported).

Acceptance:
- [ ] Admin can fully manage discovered cameras from UI.
- [ ] Runtime updates apply immediately.

---

## Phase 11 – API Surface
Guest APIs:
- [ ] `GET /api/status`
- [ ] `GET /api/metrics/summary`
- [ ] `GET /api/cameras/summary`

Admin APIs:
- [ ] `GET /api/events`
- [ ] `GET /api/events/{id}`
- [ ] `GET /api/cameras`
- [ ] `POST /api/cameras/{camera_key}`
- [ ] `POST /api/control/{name}`
- [ ] `GET /api/errors`

Acceptance:
- [ ] Role gates enforced consistently.
- [ ] Guest API responses are safe for HA iframe use.

---

## Phase 12 – Migration Tool (state.json -> SQLite)
- [ ] Add `tools/migrate_state_json_to_sqlite.py`.
- [ ] Migrate known counters/metrics/per-camera state into SQLite.
- [ ] Handle missing/unknown fields gracefully.
- [ ] Make migration idempotent.

Acceptance:
- [ ] Migration runs safely multiple times.
- [ ] Post-migration stats visible in DB/UI.

---

## Phase 13 – Release Engineering
- [ ] Single source of truth version.
- [ ] Add/update `CHANGELOG.md` with sprint entry.
- [ ] Add CI workflow (tests + lint if configured).
- [ ] Confirm Docker build still works.
- [ ] Update README:
  - [ ] config include layout
  - [ ] UI routes and auth bootstrap
  - [ ] HA iframe URL (`/ui`)
  - [ ] migration instructions

Acceptance:
- [ ] CI passes on PR.
- [ ] Docs match runtime behavior.

---

## Cross-Phase Constraints
- [ ] No new MQTT debug/explain topics beyond existing topics.
- [ ] Keep MQTT surface minimal; explainability lives in SQLite/UI.
- [ ] Preserve existing safe publish behavior for non-processed events (status-only update).
- [ ] Prefer reliability over feature breadth when tradeoffs appear.
