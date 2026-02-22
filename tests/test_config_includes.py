"""Tests for include-based config loading and schema version validation."""

from __future__ import annotations

import os
import tempfile
import textwrap
import unittest
from pathlib import Path

from src.config import load_settings
from src.errors import ConfigError

try:
    import yaml  # noqa: F401

    HAS_YAML = True
except ModuleNotFoundError:  # pragma: no cover - local env dependency gap
    HAS_YAML = False


class ConfigIncludesTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY", "test-key")

    def test_includes_merge_and_list_replace(self) -> None:
        if not HAS_YAML:
            self.skipTest("PyYAML not installed")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "config.yaml"
            confd = Path(td) / "config.d"
            confd.mkdir(parents=True, exist_ok=True)

            root.write_text(
                textwrap.dedent(
                    """
                    schema_version: 1
                    service:
                      name: Synthia Vision
                      slug: synthia_vision
                      mqtt_prefix: home/synthiavision
                      paths:
                        state_file: state/state.json
                        config_file: config/config.yaml
                        snapshots_dir: state/snapshots
                        db_file: state/synthia_vision.db
                    includes:
                      - config.d/00-base.yaml
                      - config.d/10-override.yaml
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (confd / "00-base.yaml").write_text(
                textwrap.dedent(
                    """
                    mqtt:
                      host: 127.0.0.1
                      subscribe:
                        frigate_events_topic: frigate/events
                    frigate:
                      api_base_url: http://127.0.0.1:5000
                    ai:
                      openai:
                        api_key: ${OPENAI_API_KEY}
                    policy:
                      defaults:
                        labels: [person, car]
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (confd / "10-override.yaml").write_text(
                textwrap.dedent(
                    """
                    policy:
                      defaults:
                        labels: [person]
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            cfg = load_settings(root)
            self.assertEqual(cfg.mqtt.host, "127.0.0.1")
            self.assertEqual(cfg.policy.defaults.labels, ["person"])

    def test_invalid_schema_version_fails_fast(self) -> None:
        if not HAS_YAML:
            self.skipTest("PyYAML not installed")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "config.yaml"
            root.write_text(
                textwrap.dedent(
                    """
                    schema_version: 999
                    service:
                      name: Synthia Vision
                      slug: synthia_vision
                      mqtt_prefix: home/synthiavision
                      paths:
                        state_file: state/state.json
                        config_file: config/config.yaml
                        snapshots_dir: state/snapshots
                        db_file: state/synthia_vision.db
                    mqtt:
                      host: 127.0.0.1
                      subscribe:
                        frigate_events_topic: frigate/events
                    frigate:
                      api_base_url: http://127.0.0.1:5000
                    ai:
                      openai:
                        api_key: ${OPENAI_API_KEY}
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError):
                load_settings(root)


if __name__ == "__main__":
    unittest.main()
