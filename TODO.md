# Synthia Vision – TODO (Next Sprint)

Sprint theme: **Boring runtime + local explain UI** with minimal MQTT clutter.

Execution rule:
- Complete one phase at a time.
- When asked to continue, commit the previous phase and update docs before starting the next.
- Use ./Documents/sql.md and ./Documents/schema.sql for the sql related items and schemas.

## Conventions
- [ ] Newly discovered cameras default to `enabled=false`.
- [ ] MQTT internal topics must derive from `service.mqtt_prefix`; only external topics may be hardcoded (`frigate/events`, `homeassistant/status`).
- [ ] Avoid MQTT clutter: per-event explainability stays in SQLite + UI/HTTP APIs.
- [ ] Config layering convention: `config.d/00-defaults.yaml` (repo), `config.d/99-local.yaml` (user overrides, gitignored).

---

## Phase 0 – Guardrails / Constraints
- [x] Snapshot current behavior and document known MQTT/runtime behavior.
- [x] Define constants for queue/degraded thresholds (`queue_max=50`, degrade high-water and recovery).
- [x] Add/confirm test harness for new pipeline modules.

Acceptance:
- [x] Baseline tests run.
- [x] New sprint constants/config entries are defined in one place.

---

## Phase 1 – Config Refactor + MQTT Normalization
- [x] Add root config model fields: `schema_version`, `includes`, `service.paths.db_file`.
- [x] Implement include-based loader:
- [x] Subtask: `config.yaml` as root.
- [x] Subtask: `config.d/*.yaml` merged in order.
- [x] Subtask: deep-merge dicts; lists are replace semantics.
- [x] Add schema version validation with clear failure message.
- [x] Normalize MQTT topic derivation from `service.mqtt_prefix`.
- [x] Ensure no internal hardcoded `synthia/synthiavision/...` topics remain.
- [x] Add config override precedence documentation:
- [x] Merge order: root -> config.d (sorted) -> environment overrides.
- [x] Explicitly document list replacement semantics.

Acceptance:
- [x] Existing runtime config loads via includes.
- [x] Schema mismatch fails fast with clear error.
- [x] Topic normalization verified.

---

## Phase 2 – Disable Cropping (Full-Frame Only)
- [x] Remove/disable bbox/ROI cropping paths in preprocessing.
- [x] Keep resize/compress token controls.
- [x] Ensure `input_image` blocks remain used.
- [x] Force `crop_to_bbox=false` behavior (or remove option).

Acceptance:
- [x] No crop path is active.
- [x] Token guard still works.

---

## Phase 3 – SQLite Foundation + Schema + Indexes + WAL
- [x] Add SQLite DB path default: `/app/state/synthia_vision.db`.
- [x] Implement DB init with WAL mode and sane busy timeout.
- [x] Add tables:
- [x] Subtask: `events`
- [x] Subtask: `metrics`
- [x] Subtask: `errors`
- [x] Subtask: `users`
- [x] Subtask: `kv`
- [x] Subtask: `cameras`
- [x] Add indexes:
- [x] Subtask: `events(ts)`
- [x] Subtask: `events(camera, ts)`
- [x] Subtask: `events(accepted, ts)`
- [x] Subtask: `metrics(event_id)`
- [x] Subtask: `cameras(last_seen_ts)`
- [x] Subtask: `errors(ts)`
- [x] Add DB access module (`src/db/...`) with robust write helpers.
- [x] Enable WAL mode explicitly (`PRAGMA journal_mode=WAL;`).
- [x] Set busy_timeout (>= 5000ms).
- [x] Ensure foreign_keys=ON.
- [x] Add DB schema_version table or kv entry.

Acceptance:
- [x] DB initializes on startup.
- [x] Table/index creation is idempotent.

---

## Phase 4 – Queue / Backpressure / Degraded Status
- [x] Introduce bounded intake queue (size 50).
- [x] Keep MQTT callback lightweight: parse + validate/normalize + enqueue only.
- [x] Add dedicated worker for processing queue items.
- [x] Implementation note: prefer `collections.deque(maxlen=50)` but avoid implicit auto-drop behavior; enforce drop decisions explicitly in code.
- [x] Drop policy:
- [x] Subtask: if full and incoming is `update`, drop incoming update.
- [x] Subtask: else if full, drop oldest (`popleft`) then enqueue incoming.
- [ ] Track drop counters in SQLite and summary API.
- [x] Implement degraded status transitions:
- [x] Degrade when queue > 40 for > 30s.
- [x] Recover when queue < 10.
- [x] Publish only existing status topic.
- [ ] Track queue_depth metric for summary API.

Acceptance:
- [x] Queue never exceeds 50.
- [x] MQTT thread stays responsive under burst load.
- [x] Degraded transitions behave as specified.

---

## Phase 5 – Camera Discovery + Camera Config in SQLite
- [x] Remove/ignore `policy.cameras` from YAML as source of truth.
- [x] Upsert discovered cameras from every Frigate event.
- [x] Mandatory default for new cameras: `enabled=0`.
- [x] Track `discovered_first_ts` and `last_seen_ts`.
- [x] Add transition rule for legacy YAML camera config:
- [x] Subtask: during migration window, legacy YAML camera values are ignored for runtime decisions.
- [x] Subtask: optional one-time migration tool/import may copy YAML camera values into SQLite.
- [ ] Add per-camera settings usage:
- [x] Subtask: `display_name`, `prompt_preset`, `confidence_threshold`, `cooldown_s`
- [x] Subtask: `process_end_events`, `process_update_events`, `updates_per_event`
- [ ] Subtask: `vision_detail`, `phash_threshold`
- [x] Add unique constraint on cameras.camera_key.
- [x] Do not auto-enable cameras under any circumstance.

Acceptance:
- [x] New cameras appear in SQLite automatically.
- [x] New cameras are disabled by default.

---

## Phase 6 – Event / Metrics / Error Journaling
- [x] Write one `events` row for each handled event (accepted or rejected).
- [x] Write `metrics` row when processing path runs.
- [x] Record reject reasons and skipped reasons in DB, not MQTT debug topics.
- [x] Record runtime errors in `errors` with component and short detail.
- [x] Ensure journaling is non-blocking relative to MQTT intake (writes happen in worker context only).

Acceptance:
- [x] Explainability data exists in SQLite for recent events.
- [ ] MQTT clutter does not increase.

---

## Phase 7 – Smart Update (Perceptual Hash Gating)
- [x] Implement pHash/dHash helper (`src/pipeline/phash.py` or equivalent).
- [ ] Add camera hash fields:
- [x] `cameras.last_phash TEXT NULL`
- [x] `cameras.last_phash_ts TEXT NULL`
- [ ] For `update` events:
- [x] Fetch full-frame snapshot.
- [x] Compute hash and compare against last camera hash.
- [x] If distance <= threshold, skip OpenAI and mark status accordingly.
- [ ] Persist hash metrics:
- [x] `phash`
- [x] `phash_distance`
- [x] `skipped_openai_reason` (`phash_unchanged`, etc.)
- [x] Cropping must remain permanently disabled; smart update must operate on full-frame snapshots.

Acceptance:
- [ ] Near-identical updates skip OpenAI.
- [ ] End events still run normal classification.

---

## Phase 8 – Auth + Bootstrap (Secure First Run)
- [ ] Add session-based auth with roles: `guest`, `admin`.
- [ ] Secure password hashing (bcrypt/argon2).
- [ ] First-run behavior:
- [ ] If users table empty and `ADMIN_PASSWORD` is set, create admin on startup (one-time).
- [ ] Else allow `/ui/setup/first-run` only from localhost OR only with `FIRST_RUN_TOKEN`.
- [ ] After first admin exists, disable first-run path.
- [ ] Restrict guest vs admin routes and APIs.
- [ ] Session cookies must be HTTPOnly and SameSite=Lax (or Strict).

Acceptance:
- [ ] Guest cannot access admin pages/APIs.
- [ ] First admin creation flow is hardened and documented.

---

## Phase 9 – API Surface (Guest/Admin)
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

## Phase 10 – UI Pages (FastAPI + Jinja)
- [ ] Add routes/pages:
- [ ] `/` -> `/ui`
- [ ] `/ui` guest overview (iframe-safe)
- [ ] `/ui/login`, `/ui/logout`
- [ ] `/ui/admin`, `/ui/setup`, `/ui/events`, `/ui/events/{id}`, `/ui/errors`
- [ ] Add template/layout files under `src/ui/templates`.
- [ ] Add static assets under `src/ui/static`.
- [ ] HA iframe note:
- [ ] `/ui` must remain embeddable in Home Assistant.
- [ ] Do not add restrictive `X-Frame-Options`/CSP blocking iframe embeds.
- [ ] If CSP is added later, include correct `frame-ancestors`.
- [ ] Guest overview must not leak reject_reason, skipped_openai_reason, or raw description fields.

Acceptance:
- [ ] UI is self-hosted, no external frontend toolchain.
- [ ] Guest overview has no controls or sensitive details.

---

## Phase 11 – Setup & Controls (Admin-Only)
- [ ] Setup page global settings:
- [ ] Subtask: monthly budget
- [ ] Subtask: confidence threshold
- [ ] Subtask: doorbell-only mode
- [ ] Subtask: high precision mode
- [ ] Subtask: default vision detail
- [ ] Subtask: default/update pHash threshold
- [ ] Setup page camera section from discovered cameras table.
- [ ] Allow per-camera edits and enable toggles.
- [ ] Clearly label runtime-only vs persisted changes.
- [ ] Persisted by default to SQLite `kv`: monthly budget, confidence threshold, doorbell-only mode, high precision mode, default vision detail, default/update pHash threshold, and per-camera settings.
- [ ] Runtime-only changes are temporary and reset on restart unless explicitly saved.
- [ ] UI must clearly distinguish between global defaults and per-camera overrides.

Acceptance:
- [ ] Admin can fully manage discovered cameras from UI.
- [ ] Runtime updates apply immediately.

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
- [ ] Add/validate config schema versioning in loader.
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
