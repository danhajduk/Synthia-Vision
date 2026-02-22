# Synthia Vision -- Core MQTT Device Design

Generated: 2026-02-22 01:52:07 UTC

------------------------------------------------------------------------

# Overview

This document defines the **Core MQTT Discovery design** for the Synthia
Vision device in Home Assistant.

-   Discovery Prefix: `homeassistant`
-   Runtime Prefix: `home/synthiavision` (default; configurable via `service.mqtt_prefix`)
-   Confidence values displayed as **0--100% everywhere**
-   All runtime state topics are **retained**
-   QoS: 1 recommended

------------------------------------------------------------------------

# Device Metadata

All Core entities share this device block:

-   name: `Synthia Vision`
-   identifiers: `["synthia_vision", "<node_id>"]`
-   manufacturer: `Dan Hajduk`
-   model: `Synthia Vision Node`
-   sw_version: `0.1.0`

------------------------------------------------------------------------

# Runtime Topic Structure

Base prefix:

    home/synthiavision

## Status & Heartbeat

-   `home/synthiavision/status`
-   `home/synthiavision/heartbeat_ts`

## Cost

-   `.../cost/last`
-   `.../cost/daily_total`
-   `.../cost/month2day_total`
-   `.../cost/avg_per_event`

## Tokens

-   `.../tokens/avg_per_request`
-   `.../tokens/avg_per_day`

## Events

-   `.../events/count_total`
-   `.../events/count_today`

## Controls

State topics (retained):

-   `.../control/enabled`
-   `.../control/monthly_budget`
-   `.../control/confidence_threshold`
-   `.../control/doorbell_only_mode`
-   `.../control/high_precision_mode`
-   `.../control/updates_per_event`

Command topics:

-   `.../control/enabled/set`
-   `.../control/monthly_budget/set`
-   `.../control/confidence_threshold/set`
-   `.../control/doorbell_only_mode/set`
-   `.../control/high_precision_mode/set`
-   `.../control/updates_per_event/set`

------------------------------------------------------------------------

# Core Entities (Home Assistant)

## 1. Status

-   Entity: `sensor.synthia_vision_status`
-   Topic: `.../status`
-   Icon: `mdi:brain`
-   States: `starting | enabled | budget_blocked | stopped | unavailable`

------------------------------------------------------------------------

## 2. Heartbeat

-   Entity: `sensor.synthia_vision_heartbeat`
-   Topic: `.../heartbeat_ts`
-   Device class: `timestamp`
-   Icon: `mdi:heart-pulse`

------------------------------------------------------------------------

# Cost Sensors (USD)

  -------------------------------------------------------------------------------------------
  Entity                Topic                        Icon                     Unit
  --------------------- ---------------------------- ------------------------ ---------------
  Last Cost             `.../cost/last`              mdi:currency-usd         USD

  Daily Cost            `.../cost/daily_total`       mdi:calendar-today       USD

  Month Cost            `.../cost/month2day_total`   mdi:calendar-month       USD

  Avg Cost/Event        `.../cost/avg_per_event`     mdi:calculator-variant   USD
  -------------------------------------------------------------------------------------------

------------------------------------------------------------------------

# Token Sensors

  -----------------------------------------------------------------------------------------
  Entity                Topic                          Icon                 Unit
  --------------------- ------------------------------ -------------------- ---------------
  Avg Tokens/Request    `.../tokens/avg_per_request`   mdi:counter          tokens

  Avg Tokens/Day        `.../tokens/avg_per_day`       mdi:calendar-clock   tokens/day
  -----------------------------------------------------------------------------------------

------------------------------------------------------------------------

# Event Counters

  Entity         Topic                      Icon          Unit
  -------------- -------------------------- ------------- --------
  Events Total   `.../events/count_total`   mdi:counter   events
  Events Today   `.../events/count_today`   mdi:counter   events

------------------------------------------------------------------------

# Controls

## Enabled (Switch)

-   Entity: `switch.synthia_vision_enabled`
-   State Topic: `.../control/enabled`
-   Command Topic: `.../control/enabled/set`
-   Payload: `ON` / `OFF`
-   Icon: `mdi:power`

------------------------------------------------------------------------

## Monthly Budget (Number)

-   Entity: `number.synthia_vision_monthly_budget`
-   State Topic: `.../control/monthly_budget`
-   Command Topic: `.../control/monthly_budget/set`
-   Range: 0--200
-   Step: 0.5
-   Unit: USD
-   Mode: box
-   Icon: `mdi:cash-check`

------------------------------------------------------------------------

## Confidence Threshold (Number)

-   Entity: `number.synthia_vision_confidence_threshold`
-   State Topic: `.../control/confidence_threshold`
-   Command Topic: `.../control/confidence_threshold/set`
-   Range: 0--100
-   Step: 1
-   Unit: %
-   Mode: box
-   Icon: `mdi:percent`

------------------------------------------------------------------------

## Doorbell Only Mode (Switch)

-   Entity: `switch.synthia_vision_doorbell_only_mode`
-   State Topic: `.../control/doorbell_only_mode`
-   Command Topic: `.../control/doorbell_only_mode/set`
-   Payload: `ON` / `OFF`
-   Icon: `mdi:doorbell-video`

------------------------------------------------------------------------

## High Precision Mode (Switch)

-   Entity: `switch.synthia_vision_high_precision_mode`
-   State Topic: `.../control/high_precision_mode`
-   Command Topic: `.../control/high_precision_mode/set`
-   Payload: `ON` / `OFF`
-   Icon: `mdi:target`

------------------------------------------------------------------------

## Updates Per Event (Number)

-   Entity: `number.synthia_vision_updates_per_event`
-   State Topic: `.../control/updates_per_event`
-   Command Topic: `.../control/updates_per_event/set`
-   Range: 1--2
-   Step: 1
-   Default: `1`
-   Mode: box
-   Icon: `mdi:numeric`

------------------------------------------------------------------------

# Event-Type Routing Controls

-   Per-camera controls define if `type=end` and `type=update` are processed.
-   `updates_per_event` limits accepted updates per `event_id`.
-   When an `end` event is seen, update counters for that `event_id` are reset.
-   Stale update counters are cleaned up by TTL to avoid unbounded growth.

------------------------------------------------------------------------

# Confidence Display Rule

Internally confidence may be stored as 0.0--1.0.

For Home Assistant:

-   Convert to 0--100
-   Publish as integer percentage
-   Example: 0.87 → 87

------------------------------------------------------------------------

# Best Practices

-   All state topics must be retained.
-   Re-publish discovery configs when `homeassistant/status = online`.
-   Publish control state on startup so HA syncs correctly.
-   Never publish to `homeassistant/status` (reserved for HA).

------------------------------------------------------------------------

End of Core MQTT Design
