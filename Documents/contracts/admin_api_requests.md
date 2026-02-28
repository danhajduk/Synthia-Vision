# Admin API Request Examples

These examples are derived from request normalization in `src/api/server.py`
and update handlers in `src/db/admin_store.py`.

## Auth endpoints

`POST /api/auth/login`:

```json
{
  "username": "admin",
  "password": "supersecurepass"
}
```

## Camera update endpoints

`POST /api/cameras/{camera_key}` (admin session required):

```json
{
  "enabled": true,
  "process_end_events": true,
  "process_update_events": true,
  "updates_per_event": 2,
  "display_name": "Front Door",
  "prompt_preset": "outdoor",
  "confidence_threshold": 0.6,
  "cooldown_s": 30,
  "vision_detail": "low",
  "phash_threshold": 6,
  "guest_preview_enabled": true,
  "security_capable": true,
  "security_mode": false
}
```

Notes:
- `updates_per_event` is clamped to `1..2`.
- `confidence_threshold` accepts `0..1` and also percent-like numbers (>1 interpreted as percent).
- `vision_detail` accepted values: `low`, `high`.

`POST /api/admin/cameras/{camera_key}/apply` (runtime-only, not persisted):

```json
{
  "enabled": false,
  "guest_preview_enabled": false,
  "confidence_threshold": 0.7
}
```

`POST /api/admin/cameras/{camera_key}/save` (persisted):

```json
{
  "enabled": false,
  "guest_preview_enabled": false,
  "confidence_threshold": 0.7
}
```

## Control update endpoint

`POST /api/control/{name}`:

```json
{
  "value": 0.65
}
```

Example names:
- `enabled`
- `monthly_budget`
- `confidence_threshold`
- `doorbell_only_mode`
- `high_precision_mode`
- `updates_per_event`

## Admin settings endpoints

`POST /api/admin/settings/apply` (runtime preview):

```json
{
  "budget.monthly_limit_usd": 20.0,
  "policy.defaults.confidence_threshold": 0.55,
  "ui.preview_enabled": true,
  "ui.preview_enabled_interval_s": 2,
  "ui.preview_disabled_interval_s": 60,
  "ui.preview_max_active": 1
}
```

`POST /api/admin/settings/save` (persist values):

```json
{
  "budget.monthly_limit_usd": 20.0,
  "policy.defaults.confidence_threshold": 0.55,
  "ui.preview_enabled": true
}
```

## Setup context generation

`POST /api/admin/cameras/{camera_key}/views/{view_id}/setup/generate_context`:

```json
{
  "environment": "outdoor",
  "purpose": "doorbell",
  "view_type": "fixed",
  "mounting_location": "front_porch",
  "view_notes": "Main front-door view",
  "delivery_focus": ["package"]
}
```

Allowed `purpose` values:
- `general`
- `doorbell`
- `perimeter_security`
- `driveway`
- `backyard`
- `garage`
- `child_room`

