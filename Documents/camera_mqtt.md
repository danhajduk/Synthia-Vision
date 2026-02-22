# Synthia Vision -- Per-Camera MQTT Device Design

Generated: 2026-02-22 01:57:52 UTC

------------------------------------------------------------------------

# Overview

This document defines the **per-camera MQTT Discovery design** for
Synthia Vision in Home Assistant.

Design goals: - **Option A**: Each camera appears as a **separate HA
Device** - Camera entities are clean and minimal (no internal/debug
noise) - Confidence is displayed as **0--100%** - All runtime topics are
**retained** - QoS: 1 recommended

Discovery Prefix: `homeassistant`\
Runtime Prefix: `home/synthiavision` (default; configurable via `service.mqtt_prefix`)

------------------------------------------------------------------------

# Camera Device Metadata

Each camera device shares a common pattern:

-   name: `<CameraName>` (example: `Front Door`)
-   identifiers: `["<camera>"]`
    -   example: `["doorbell"]`
-   manufacturer: `Dan Hajduk`
-   model: `Synthia Vision Camera`
-   sw_version: `0.1.0`
-   via_device: `synthia_vision`

------------------------------------------------------------------------

# Runtime Topic Structure (Per Camera)

Camera topics use `{camera}` as a placeholder.

Base prefix:

    home/synthiavision

Per-camera state topics:

-   `.../camera/{camera}/enabled` (`ON|OFF`)
-   `.../camera/{camera}/process_end_events` (`ON|OFF`)
-   `.../camera/{camera}/process_update_events` (`ON|OFF`)
-   `.../camera/{camera}/action`
-   `.../camera/{camera}/subject_type`
-   `.../camera/{camera}/confidence` (0--100 integer)
-   `.../camera/{camera}/description`
-   `.../camera/{camera}/result_status`
-   `.../camera/{camera}/last_event_id`
-   `.../camera/{camera}/last_event_ts` (ISO timestamp)

Per-camera cost topic (published by Core cost module):

-   `.../cost/monthly_by_camera/{camera}`

------------------------------------------------------------------------

Per-camera command topic:

-   `.../camera/{camera}/enabled/set` (`ON|OFF`)
-   `.../camera/{camera}/process_end_events/set` (`ON|OFF`)
-   `.../camera/{camera}/process_update_events/set` (`ON|OFF`)

------------------------------------------------------------------------

# Per-Camera Entities (Home Assistant)

## 1) Enabled (Switch)

-   Entity: `switch.sv_<camera>_enabled`
-   Name: `Enabled`
-   State Topic: `.../camera/{camera}/enabled`
-   Command Topic: `.../camera/{camera}/enabled/set`
-   Payload: `ON` / `OFF`
-   Icon: `mdi:power`

------------------------------------------------------------------------

## 2) Action (Enum Sensor)

-   Entity: `sensor.sv_<camera>_action`
-   Name: `Action`
-   Topic: `.../camera/{camera}/action`
-   Icon: choose one:
    -   Doorbell-style cameras: `mdi:doorbell-video`
    -   General cameras: `mdi:cctv`

Suggested action values (expandable): - `unknown` - `deliver_package` -
`pickup_package` - `package_left_unattended` - `vehicle_arrival` -
`vehicle_departure` - `vehicle_detected` - `delivery_vehicle` -
`loitering` - `suspicious_activity` - `animal_detected` -
`person_entered` - `person_exited` - `in_bed` - `out_of_bed` -
`room_occupied`

## 2a) Process End Events (Switch)

-   Entity: `switch.sv_<camera>_process_end_events`
-   Name: `Process End Events`
-   State Topic: `.../camera/{camera}/process_end_events`
-   Command Topic: `.../camera/{camera}/process_end_events/set`
-   Default: `ON`
-   Payload: `ON` / `OFF`
-   Icon: `mdi:flag-checkered`

## 2b) Process Update Events (Switch)

-   Entity: `switch.sv_<camera>_process_update_events`
-   Name: `Process Update Events`
-   State Topic: `.../camera/{camera}/process_update_events`
-   Command Topic: `.../camera/{camera}/process_update_events/set`
-   Default: `OFF`
-   Payload: `ON` / `OFF`
-   Icon: `mdi:update`

## 3) Confidence (Sensor, 0--100)

-   Entity: `sensor.sv_<camera>_confidence`
-   Name: `Confidence`
-   Topic: `.../camera/{camera}/confidence`
-   Unit: `%`
-   Icon: `mdi:percent`

Rule: - Publish integer percent. Example: 0.87 → 87.

## 3a) Subject Type (Enum Sensor)

-   Entity: `sensor.sv_<camera>_subject_type`
-   Name: `Subject Type`
-   Topic: `.../camera/{camera}/subject_type`
-   Icon: `mdi:tag`

Suggested values: `none | adult | child | pet | animal | vehicle | unknown`.

## 4) Description (Sensor)

-   Entity: `sensor.sv_<camera>_description`
-   Name: `Description`
-   Topic: `.../camera/{camera}/description`
-   Icon: `mdi:text`

Guidance: - Keep it short (\<= 200 chars) - Factual and non-creative
(automation-friendly)

## 5) Result Status (Enum Sensor)

-   Entity: `sensor.sv_<camera>_result_status`
-   Name: `Result Status`
-   Topic: `.../camera/{camera}/result_status`
-   Icon: `mdi:shield-alert`

Suggested status values: - `ok` - `snapshot_failed` - `openai_failed` -
`schema_failed` - `token_budget_exceeded` - `blocked_budget` -
`invalid_action` - `invalid_subject_type` - `skipped` (policy reject;
typically not published for suppressed events) - `suppressed`
(cooldown/dedupe; typically not published)

Recommendation: - Only publish per-camera results for accepted events. -
Use counters/logs for suppressed/ignored noise instead.

## 6) Last Event ID (Sensor)

-   Entity: `sensor.sv_<camera>_last_event_id`
-   Name: `Last Event ID`
-   Topic: `.../camera/{camera}/last_event_id`
-   Icon: `mdi:identifier`

## 7) Last Event Time (Timestamp Sensor)

-   Entity: `sensor.sv_<camera>_last_event_ts`
-   Name: `Last Event Time`
-   Topic: `.../camera/{camera}/last_event_ts`
-   Device class: `timestamp`
-   Icon: `mdi:clock-outline`

## 8) Monthly Cost (USD Sensor)

-   Entity: `sensor.sv_<camera>_monthly_cost`
-   Name: `Monthly Cost`
-   Topic: `.../cost/monthly_by_camera/{camera}`
-   Unit: `USD`
-   Icon: `mdi:currency-usd`

------------------------------------------------------------------------

# Discovery Naming Rules (Anti-Dupe)

## Unique ID pattern

Use a stable pattern that includes node_id and camera key:

-   `sv_<node_id>_<camera>_<entity_key>`

Examples: - `sv_homeassistant_pc_01_doorbell_action` -
`sv_homeassistant_pc_01_doorbell_confidence` -
`sv_homeassistant_pc_01_doorbell_result_status`

------------------------------------------------------------------------

# Publish Order Recommendation

When publishing a camera result, publish in this order:

1.  last_event_id
2.  last_event_ts
3.  result_status
4.  action
5.  subject_type
6.  confidence
7.  description
8.  monthly_by_camera (optional if updated elsewhere)

Reason: - "identity and time" update first, then the interpretation.

------------------------------------------------------------------------

# Best Practices

-   All camera state topics should be retained.
-   Keep `description` concise to avoid HA UI clutter.
-   Prefer consistent action/status enums over freeform strings.
-   Do not publish suppressed events as if they were real events:
    -   Track suppression in counters/logs instead.

------------------------------------------------------------------------

End of Per-Camera MQTT Design
