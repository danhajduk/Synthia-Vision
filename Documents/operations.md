# Operations Guide

This document describes current operational behavior and safe maintenance workflows.

## Runtime data locations

Default paths (container runtime):

- SQLite DB: `/app/state/synthia_vision.db`
- State JSON: `/app/state/state.json`
- Snapshots: `/app/state/snapshots/`
- Logs: `/app/logs/`

Configured from:
- `service.paths.db_file`
- `service.paths.state_file`
- `service.paths.snapshots_dir`
- `logging.files.*`

## Daily/monthly rollovers (current behavior)

Metric rollover logic resets:

- Daily rollover (date change):
  - `count_today -> 0`
  - `cost_daily_total -> 0.0`
- Monthly rollover (month key change):
  - `cost_month2day_total -> 0.0`
  - `cost_monthly_by_camera -> {}`

This behavior is applied in runtime metric maintenance (`_apply_metric_rollovers`).

## Backup and restore (SQLite)

### Backup

Stop writes first (recommended) by stopping service/container, then:

```bash
cp state/synthia_vision.db state/synthia_vision.db.bak.$(date +%F-%H%M%S)
```

Or use SQLite online backup:

```bash
sqlite3 state/synthia_vision.db ".backup 'state/synthia_vision.db.backup'"
```

### Restore

1. Stop service/container.
2. Replace DB file with backup.
3. Start service/container.

```bash
cp state/synthia_vision.db.backup state/synthia_vision.db
docker compose up -d
```

## Legacy migration notes (current support)

### YAML camera policy -> SQLite cameras

One-time import tool:

```bash
python tools/migrate_policy_cameras_to_sqlite.py --dry-run
python tools/migrate_policy_cameras_to_sqlite.py --overwrite
```

Use `--dry-run` first to verify intended changes.

### State file compatibility

- Current runtime still persists policy/runtime state in JSON (`state_file`) and journals operational records in SQLite.
- Do not manually edit either file while the service is running.

## Operational checks

After restart or migration:

- `GET /api/status` returns expected `service_status`.
- `GET /api/metrics/summary` returns valid numeric metrics.
- `/ui` renders and camera cards load.
- MQTT status topic publishes retained runtime state.

