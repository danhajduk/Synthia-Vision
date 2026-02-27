#!/usr/bin/env python3
"""Run one event classification and verify final action."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from src.ai import preprocess_image_bytes
from src.config import load_settings
from src.errors import ExternalServiceError, ValidationError
from src.models import FrigateEvent, OpenAIClassification
from src.openai.client import OpenAIClient
from src.openai.policy_helpers import (
    apply_outdoor_action_heuristic,
    build_camera_context_fields,
    enforce_classification_result,
    render_prompts,
    resolve_allowed_actions,
    resolve_preset,
    resolve_subject_types,
    _should_force_person_at_door,
)
from src.snapshot_manager import SnapshotManager


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run single-event classification regression check")
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--expected-action", default="person_at_door")
    parser.add_argument("--print-prompts", action="store_true")
    parser.add_argument("--force-proximity-override", action="store_true")
    return parser.parse_args()


def _fetch_event_payload(base_url: str, event_id: str) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/events/{event_id}"
    with urlopen(url, timeout=20) as response:  # nosec B310 - trusted local service URL
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("event payload is not a JSON object")
    return data


def _event_bbox_pixels(payload: dict[str, Any], frame_size: tuple[int, int]) -> tuple[int, int, int, int] | None:
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    box = data.get("box")
    if not (isinstance(box, list) and len(box) == 4):
        return None
    try:
        x, y, w, h = (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
    except Exception:
        return None
    fw, fh = frame_size
    if fw <= 0 or fh <= 0:
        return None
    px = int(x * fw)
    py = int(y * fh)
    pw = max(1, int(w * fw))
    ph = max(1, int(h * fh))
    return (px, py, pw, ph)


def _area_ratio(payload: dict[str, Any], frame_size: tuple[int, int], bbox: tuple[int, int, int, int] | None) -> str:
    data = payload.get("data")
    if isinstance(data, dict):
        box = data.get("box")
        if isinstance(box, list) and len(box) == 4:
            try:
                return f"{float(box[2]) * float(box[3]):.6f}"
            except Exception:
                pass
    if bbox is None:
        return "n/a"
    fw, fh = frame_size
    if fw <= 0 or fh <= 0:
        return "n/a"
    return f"{(bbox[2] * bbox[3]) / float(fw * fh):.6f}"


def main() -> int:
    args = _parse_args()
    try:
        config = load_settings()
        if args.force_proximity_override:
            config.ai.proximity_override.enabled = True

        event_payload = _fetch_event_payload(config.frigate.base_url, args.event_id)
        camera_name = str(event_payload.get("camera") or "").strip()
        if not camera_name:
            raise RuntimeError("event payload missing camera")

        snapshot_manager = SnapshotManager(config)
        snapshot_bytes = snapshot_manager.fetch_event_snapshot(args.event_id, camera=camera_name)
        snapshot_identifier = f"frigate:event:{args.event_id}"

        allowed_actions = resolve_allowed_actions(camera_name, config)
        allowed_subject_types = resolve_subject_types(config)
        context_fields = build_camera_context_fields(camera_name, config)
        preset = resolve_preset(camera_name, config, context_fields=context_fields)
        system_prompt, user_prompt = render_prompts(
            preset=preset,
            camera_name=camera_name,
            allowed_actions=allowed_actions,
            allowed_subject_types=allowed_subject_types,
            config=config,
            context_fields=context_fields,
        )

        processed = preprocess_image_bytes(
            snapshot_bytes,
            config=config,
            camera_name=camera_name,
            bbox=None,
        )
        bbox = _event_bbox_pixels(event_payload, frame_size=processed.original_size)

        client = OpenAIClient(config)
        detail = client._resolve_vision_detail(camera_name, force_low_budget=False)
        request_payload = client._build_request_payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_bytes=processed.image_bytes,
            allowed_actions=allowed_actions,
            allowed_subject_types=allowed_subject_types,
            detail=detail,
        )
        response = client._request_with_retry(payload=request_payload)
        raw_text = client._extract_text_response(response)
        raw_model_json = client._parse_json_payload(raw_text)
        classification = OpenAIClassification.from_dict(raw_model_json)

        event = FrigateEvent(
            event_id=args.event_id,
            camera=camera_name,
            label=str(event_payload.get("label") or "person"),
            event_type="end",
            bbox=bbox,
        )
        frame_size = processed.processed_size
        proximity_override_triggered = _should_force_person_at_door(
            event=event,
            action=classification.action,
            config=config,
            frame_size=frame_size,
        )
        action_after_heuristic = apply_outdoor_action_heuristic(
            event=event,
            action=classification.action,
            config=config,
            frame_size=frame_size,
        )
        final_action, final_subject_type, final_description, result_status = enforce_classification_result(
            action=action_after_heuristic,
            subject_type=classification.subject_type,
            description=classification.description,
            camera=camera_name,
            config=config,
        )

        final_json = {
            "action": final_action,
            "subject_type": final_subject_type,
            "confidence": classification.confidence,
            "description": final_description,
            "result_status": result_status,
        }

        output = {
            "event_id": args.event_id,
            "camera_name": camera_name,
            "snapshot_identifier": snapshot_identifier,
            "system_prompt_chars": len(system_prompt),
            "user_prompt_chars": len(user_prompt),
            "raw_model_json": raw_model_json,
            "final_json": final_json,
            "proximity_override_triggered": bool(proximity_override_triggered),
            "area_ratio": _area_ratio(event_payload, frame_size, bbox),
            "right_edge_touch_ratio": (
                f"{float(config.ai.proximity_override.right_edge_touch_ratio):.2f}"
                if bbox is not None
                else "n/a"
            ),
        }
        print(json.dumps(output, ensure_ascii=True))

        if args.print_prompts:
            print("----- SYSTEM PROMPT -----")
            print(system_prompt)
            print("----- USER PROMPT -----")
            print(user_prompt)

        if final_action != args.expected_action:
            return 2
        return 0
    except (ExternalServiceError, ValidationError, URLError, RuntimeError, ValueError, KeyError) as exc:
        print(json.dumps({"error": str(exc), "event_id": args.event_id}, ensure_ascii=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
