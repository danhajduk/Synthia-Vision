# Home Assistant Integration

This guide covers currently supported HA integration behavior.

## Current behavior

- Guest dashboard is available at `/ui` and is iframe-friendly.
- In embedded mode (`/ui` in HA iframe):
  - guest top bar is hidden
  - guest footer is hidden
  - an `Admin` link is shown for opening `/ui/login` in a new tab
- MQTT discovery is published when enabled (`mqtt.discovery.enabled=true`).

## HA dashboard iframe guidance

Use an HA webpage/iframe card pointed at:

```text
http://<synthia-host>:8080/ui
```

Recommended:
- keep the card in guest mode for daily monitoring.
- use `/ui/login` in a separate tab for admin-only controls.

## MQTT discovery overview (high-level)

Core entities include:
- service status + heartbeat sensors
- cost sensors (last, daily total, month-to-date, avg/event)
- token sensors (avg/request, avg/day)
- event counters (today, total)
- core controls (enabled, monthly budget, confidence threshold, doorbell-only mode, high-precision mode, updates-per-event)

Per-camera entities include:
- switches: enabled, process end events, process update events
- sensors: action, confidence, subject_type, description, result_status, last_event_id, last_event_ts, monthly_cost

Discovery config topics are published under:

```text
<discovery_prefix>/<component>/<node_id>/<entity>/config
```

Defaults are driven by config values in `config/config.d/10-mqtt.yaml`.

## Example HA automation snippet

Example: notify when a camera enters `suspicious_activity`.

```yaml
alias: Synthia suspicious activity alert
mode: single
trigger:
  - platform: mqtt
    topic: home/synthiavision/camera/doorbell/action
condition:
  - condition: template
    value_template: "{{ trigger.payload == 'suspicious_activity' }}"
action:
  - service: persistent_notification.create
    data:
      title: Synthia Alert
      message: "Doorbell camera reported suspicious activity."
```

## Planned vs current

- Current: iframe guest UI + MQTT discovery entities + MQTT command/control paths.
- Planned: no additional HA-specific capabilities are documented here beyond what is currently implemented.

