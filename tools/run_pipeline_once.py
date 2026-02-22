#!/usr/bin/env python3
"""Offline single-run pipeline simulator without Frigate/OpenAI network calls."""

from __future__ import annotations

import argparse
import io
import json
import time
from pathlib import Path

from src.ai import preprocess_image_bytes
from src.config import load_settings
from src.models import FrigateEvent
from src.openai import enforce_classification_result
from src.policy_engine import should_process
from src.state_manager import StateManager


def _fake_snapshot_bytes() -> bytes:
    try:
        from PIL import Image
    except ModuleNotFoundError:
        # Fallback minimal JPEG (valid tiny image payload).
        return bytes.fromhex(
            "ffd8ffe000104a46494600010101006000600000ffdb004300"
            "080606070605080707070909080a0c140d0c0b0b0c19120f13"
            "1d1a1f1e1d1a1c1c202427302925222c231c1c28372a2c3031"
            "3434341f27393d38323c2e333432ffda000c03010002110311"
            "003f00d2cf20ffd9"
        )

    image = Image.new("RGB", (1280, 720), color=(90, 100, 130))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one local pipeline simulation.")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--camera", default="livingroom")
    parser.add_argument("--event-type", default="end", choices=["new", "update", "end"])
    parser.add_argument("--label", default="person")
    args = parser.parse_args()

    cfg = load_settings(Path(args.config))
    state_manager = StateManager(cfg.state_file)
    state = state_manager.load_state()
    event_payload = {
        "type": args.event_type,
        "time": time.time(),
        "after": {
            "id": f"{time.time():.6f}-offline",
            "camera": args.camera,
            "label": args.label,
            "score": 0.92,
            "start_time": time.time() - 2,
            "end_time": time.time(),
            "box": [200, 120, 300, 300],
        },
    }
    event = FrigateEvent.from_mqtt_payload(event_payload)
    decision = should_process(event=event, state=state, config=cfg)
    if not decision.should_process:
        print(json.dumps({"route": "rejected", "reason": decision.reason, "details": decision.details}))
        return 0

    snapshot = _fake_snapshot_bytes()
    preprocess = preprocess_image_bytes(
        snapshot,
        config=cfg,
        camera_name=event.camera,
        bbox=event.bbox,
    )
    # Mock classification payload (OpenAI not called in this tool).
    raw_action = "room_occupied"
    raw_subject_type = "unknown"
    raw_description = "people visible in room"
    action, subject_type, description, result_status = enforce_classification_result(
        action=raw_action,
        subject_type=raw_subject_type,
        description=raw_description,
        camera=event.camera,
        config=cfg,
    )
    result = {
        "route": "processing",
        "event_id": event.event_id,
        "camera": event.camera,
        "action": action,
        "subject_type": subject_type,
        "result_status": result_status,
        "preprocess": {
            "original_size": preprocess.original_size,
            "processed_size": preprocess.processed_size,
            "cropped_to_bbox": preprocess.cropped_to_bbox,
            "image_bytes": len(preprocess.image_bytes),
        },
        "description": description,
    }
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
