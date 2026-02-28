# Guest API Payload Examples

These examples are aligned to the active guest endpoints in `src/api/server.py`
and guest payload shaping in `src/db/summary_store.py`.

## `GET /api/status`

Example:

```json
{
  "service_status": "enabled",
  "db_ready": true,
  "heartbeat_ts": "2026-02-28T18:22:04.193815+00:00",
  "timestamp": "2026-02-28T18:22:04.204512+00:00"
}
```

## `GET /api/metrics/summary`

Example:

```json
{
  "metrics": {
    "count_total": 142,
    "ai_calls_today": 14,
    "count_today": 14,
    "count_today_date": "2026-02-28",
    "queue_depth": 0,
    "dropped_events_total": 2,
    "dropped_update_total": 1,
    "dropped_queue_full_total": 1,
    "cost_last": 0.0012,
    "cost_daily_total": 0.0184,
    "cost_month2day_total": 1.1431,
    "cost_avg_per_event": 0.0080507042,
    "avg_cost_per_event_usd": 0.0080507042,
    "tokens_avg_per_request": 318.5,
    "tokens_avg_per_day": 4459.0,
    "tokens_today_total": 4890,
    "avg_tokens_per_event": 349.2857142857,
    "cost_monthly_by_camera": {
      "doorbell": 0.8421,
      "livingroom": 0.301
    }
  }
}
```

## `GET /api/cameras/summary`

Only setup-completed cameras are returned.

Example:

```json
{
  "count": 2,
  "items": [
    {
      "camera_key": "doorbell",
      "display_name": "Front Door",
      "enabled": true,
      "last_seen_ts": "2026-02-28T18:21:43+00:00",
      "monthly_cost": 0.8421
    },
    {
      "camera_key": "livingroom",
      "display_name": "Living Room",
      "enabled": false,
      "last_seen_ts": "2026-02-28T18:19:07+00:00",
      "monthly_cost": 0.301
    }
  ]
}
```

## `GET /api/cameras/{camera_key}/card`

Example:

```json
{
  "camera_key": "doorbell",
  "display_name": "Front Door",
  "enabled": true,
  "status": "ok",
  "last_seen_ts": "2026-02-28T18:21:43+00:00",
  "last_action_confidence": "person_at_door (97%)",
  "mtd_cost": "$0.8421"
}
```

## `POST /api/cameras/{camera_key}/toggle`

Example response:

```json
{
  "ok": true,
  "camera_key": "doorbell",
  "enabled": false
}
```

