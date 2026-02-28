# MQTT Topic Contracts

This document captures the most important MQTT topic families and payload examples.

Runtime prefix examples use default: `home/synthiavision`.

## Topic families

| Family | Direction | Payload type | Retained |
|---|---|---|---|
| `frigate/events` | inbound (Frigate -> Synthia) | JSON object | producer-defined (typically non-retained) |
| `home/synthiavision/status` | outbound | string enum | yes |
| `home/synthiavision/heartbeat_ts` | outbound | ISO timestamp string | yes |
| `home/synthiavision/events/*` | outbound | numeric string | yes |
| `home/synthiavision/cost/*` | outbound | numeric string | yes |
| `home/synthiavision/tokens/*` | outbound | numeric string | yes |
| `home/synthiavision/camera/{camera}/*` | outbound | string / enum / numeric string | yes |
| `home/synthiavision/control/*/set` | inbound command | string / number-like string | usually non-retained |
| `home/synthiavision/camera/{camera}/*/set` | inbound command | `ON`/`OFF` | usually non-retained |

Retention note:
- Outbound retention is configured by `mqtt.publish.retain` (default `true` in current config).

## Core status and metrics examples

```text
topic: home/synthiavision/status
payload: enabled
```

```text
topic: home/synthiavision/heartbeat_ts
payload: 2026-02-28T18:22:04.193815+00:00
```

```text
topic: home/synthiavision/events/count_today
payload: 14
```

```text
topic: home/synthiavision/cost/month2day_total
payload: 1.2345
```

## Per-camera output examples

```text
topic: home/synthiavision/camera/doorbell/enabled
payload: ON
```

```text
topic: home/synthiavision/camera/doorbell/result_status
payload: ok
```

```text
topic: home/synthiavision/camera/doorbell/action
payload: person_at_door
```

```text
topic: home/synthiavision/camera/doorbell/confidence
payload: 97
```

```text
topic: home/synthiavision/camera/doorbell/description
payload: person standing at entry threshold
```

## Command topic examples

```text
topic: home/synthiavision/control/monthly_budget/set
payload: 25.00
```

```text
topic: home/synthiavision/control/confidence_threshold/set
payload: 0.65
```

```text
topic: home/synthiavision/camera/doorbell/enabled/set
payload: OFF
```

