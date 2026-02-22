#!/usr/bin/env python3
"""One-time import of legacy policy.cameras YAML values into SQLite cameras table."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config import load_settings
from src.db import CameraStore, DatabaseBootstrap


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import config policy.cameras values into SQLite camera rows.",
    )
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        help="Root config file path (default: config/config.yaml)",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="SQLite DB path override (default: config service.paths.db_file)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing camera rows instead of skipping existing keys.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print intended operations without writing to SQLite.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    settings = load_settings(config_path)
    db_path = Path(args.db) if args.db else Path(settings.paths.db_file)

    if not args.dry_run:
        DatabaseBootstrap(db_path=db_path, schema_sql_path=Path("Documents/schema.sql")).initialize()

    store = CameraStore(db_path)
    imported = 0
    skipped = 0
    for camera_key, camera_cfg in sorted(settings.policy.cameras.items()):
        exists = store.get_camera_enabled(camera_key) is not None if db_path.exists() else False
        if exists and not args.overwrite:
            print(f"skip camera={camera_key} reason=exists")
            skipped += 1
            continue

        display_name = camera_cfg.name or camera_key.replace("_", " ").title()
        prompt_preset = camera_cfg.prompt_preset
        vision_detail = camera_cfg.vision_detail or settings.ai.vision_detail
        if args.dry_run:
            print(
                "import"
                f" camera={camera_key}"
                f" enabled={camera_cfg.enabled}"
                f" confidence_threshold={camera_cfg.confidence_threshold}"
                f" cooldown_s={camera_cfg.cooldown_seconds}"
                f" prompt_preset={prompt_preset or '-'}"
                f" vision_detail={vision_detail}"
            )
            imported += 1
            continue

        store.upsert_discovered_camera(camera_key)
        store.set_camera_policy_fields(
            camera_key,
            display_name=display_name,
            prompt_preset=prompt_preset,
            confidence_threshold=camera_cfg.confidence_threshold,
            cooldown_s=camera_cfg.cooldown_seconds,
            vision_detail=vision_detail,
            enabled=camera_cfg.enabled,
        )
        imported += 1
        print(f"imported camera={camera_key}")

    print(
        f"done imported={imported} skipped={skipped} overwrite={bool(args.overwrite)} dry_run={bool(args.dry_run)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
