# Synthia Vision

### Frigate + OpenAI + MQTT + Home Assistant

Generated: 2026-02-21 18:07:19 UTC

------------------------------------------------------------------------

## Overview

**Synthia Vision** is a standalone, event-aware AI service that replaces
Frigate's built-in GenAI integration.

Architecture:

Frigate → MQTT Events → Synthia Vision → OpenAI → MQTT (Structured
Output + Cost/State) → Home Assistant

Synthia Vision is:

-   A stateful AI event processor
-   A policy engine
-   A cost tracker (token-accurate)
-   A budget guard
-   A rate limiter / cooldown manager
-   An HA-native MQTT Discovery device
-   Future multi-provider ready

------------------------------------------------------------------------

## Base Configuration

-   Project Folder: \~/Projects/HomeAssistant/synthia_vision/

-   MQTT Namespace: home/synthiavision/

-   HA Device Name: Synthia Vision

-   HA Device Identifier: synthia_vision

------------------------------------------------------------------------

## Core Responsibilities

1.  Subscribe to `frigate/events`
2.  Validate and filter events
3.  Apply per-camera policy rules
4.  Dedupe and cooldown suppress
5.  Fetch event snapshot from Frigate API
6.  Send snapshot to OpenAI (strict JSON schema)
7.  Track exact token usage + cost
8.  Persist state atomically
9.  Publish structured results + cost metrics to MQTT
10. Register HA MQTT Discovery entities

------------------------------------------------------------------------

## OpenAI Structured Output Schema

Example:

``` json
{
  "action": "deliver_package",
  "confidence": 0.87,
  "description": "Person places a small box near the door."
}
```

Required fields: - action (string) - confidence (0..1 float) -
description (string)

------------------------------------------------------------------------

## MQTT Topics

### Subscribed

-   frigate/events

### Published (Per Camera)

-   home/synthiavision/camera/`<camera>`{=html}/action
-   home/synthiavision/camera/`<camera>`{=html}/confidence
-   home/synthiavision/camera/`<camera>`{=html}/description
-   home/synthiavision/camera/`<camera>`{=html}/last_event_id
-   home/synthiavision/camera/`<camera>`{=html}/last_event_ts

### Published (Cost Metrics)

-   home/synthiavision/cost/last
-   home/synthiavision/cost/daily_total
-   home/synthiavision/cost/month2day_total
-   home/synthiavision/cost/avg_per_event
-   home/synthiavision/cost/monthly_by_camera/`<camera>`{=html}

### Published (Status & Counters)

-   home/synthiavision/status
-   home/synthiavision/events/count_total
-   home/synthiavision/events/count_today

All state topics should be retained.

------------------------------------------------------------------------

## Persistent State Model (state.json)

``` json
{
  "last_reset": "2026-02-01",
  "cost": {
    "month2day_total": 2.43,
    "daily_total": 0.12,
    "avg_per_event": 0.0165,
    "last_cost": 0.012,
    "monthly_by_camera": {
      "doorbell": 1.73
    }
  },
  "events": {
    "count_total": 147,
    "count_today": 12,
    "recent_event_ids": [],
    "last_by_camera": {}
  },
  "settings": {
    "enabled": true,
    "doorbell_only_mode": true,
    "high_precision_mode": false,
    "monthly_budget_limit": 10.0,
    "confidence_threshold": 0.75
  }
}
```

Writes must be atomic.

------------------------------------------------------------------------

## Folder Structure

    synthia_vision/
    ├── docker/
    │   ├── Dockerfile
    │   └── docker-compose.yml
    ├── src/
    │   ├── main.py
    │   ├── mqtt_handler.py
    │   ├── event_router.py
    │   ├── policy_engine.py
    │   ├── snapshot_manager.py
    │   ├── openai_client.py
    │   ├── state_manager.py
    │   ├── ha_discovery.py
    │   ├── models.py
    │   └── utils.py
    ├── config/
    │   └── config.yaml
    ├── state/
    │   └── state.json
    ├── logs/
    ├── requirements.txt
    └── README.md

------------------------------------------------------------------------

## Deployment

-   Standalone Docker container
-   Bind mount config/ and state/
-   Use environment variables for API keys
-   Provide health endpoint
-   Run on same host as Frigate + HA + MQTT

------------------------------------------------------------------------

## MVP Scope

-   MQTT listener
-   Policy engine (end-only + person)
-   Snapshot fetch via Frigate event endpoint
-   OpenAI structured classifier
-   Token-accurate cost tracking
-   Persistent state
-   MQTT publishing
-   HA MQTT Discovery integration

------------------------------------------------------------------------

End of Synthia Vision Blueprint
