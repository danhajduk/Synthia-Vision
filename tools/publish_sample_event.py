#!/usr/bin/env python3
"""Publish a canned Frigate-style event to MQTT."""

from __future__ import annotations

import argparse
import json
import time

import paho.mqtt.client as mqtt


def build_payload(camera: str, label: str, event_type: str, event_id: str | None) -> dict[str, object]:
    now = time.time()
    generated_id = event_id or f"{now:.6f}-sample"
    return {
        "type": event_type,
        "time": now,
        "after": {
            "id": generated_id,
            "camera": camera,
            "label": label,
            "score": 0.91,
            "start_time": now - 2.0,
            "end_time": now,
            "box": [120, 80, 300, 300],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a sample Frigate event.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--topic", default="frigate/events")
    parser.add_argument("--camera", default="livingroom")
    parser.add_argument("--label", default="person")
    parser.add_argument("--type", default="end", choices=["new", "update", "end"])
    parser.add_argument("--event-id", default=None)
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    args = parser.parse_args()

    payload = build_payload(args.camera, args.label, args.type, args.event_id)
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    if args.username:
        client.username_pw_set(args.username, args.password)
    client.connect(args.host, args.port, 30)
    data = json.dumps(payload, separators=(",", ":"))
    info = client.publish(args.topic, data, qos=1, retain=False)
    info.wait_for_publish()
    client.disconnect()
    print(f"published topic={args.topic} event_id={payload['after']['id']} camera={args.camera} type={args.type}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
