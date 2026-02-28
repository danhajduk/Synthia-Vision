"""Configuration loading for Synthia Vision."""

from __future__ import annotations

import os
import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.errors import ConfigError

LOGGER = logging.getLogger("synthia_vision.config")

ENV_PLACEHOLDER_PATTERN = re.compile(r"^\$\{([A-Z0-9_]+)\}$")
SUPPORTED_CONFIG_SCHEMA_VERSION = 1


@dataclass(slots=True)
class AppConfig:
    log_level: str = "INFO"


@dataclass(slots=True)
class LoggingComponentLevels:
    core: str = "INFO"
    mqtt: str = "INFO"
    config: str = "INFO"
    policy: str = "INFO"
    ai: str = "INFO"


@dataclass(slots=True)
class LoggingConfig:
    level: str = "INFO"
    file: str | None = None
    json: bool = False
    retention_days: int = 14
    components: LoggingComponentLevels = field(default_factory=LoggingComponentLevels)


@dataclass(slots=True)
class LoggingComponentFiles:
    core: str | None = None
    mqtt: str | None = None
    config: str | None = None
    policy: str | None = None
    ai: str | None = None


@dataclass(slots=True)
class ServiceIdentityConfig:
    name: str = "Synthia Vision"
    slug: str = "synthia_vision"
    mqtt_prefix: str = "home/synthiavision"


@dataclass(slots=True)
class ServicePathsConfig:
    state_file: Path = Path("state/state.json")
    config_file: Path = Path("config/config.yaml")
    snapshots_dir: Path = Path("state/snapshots")
    db_file: Path = Path("state/synthia_vision.db")


@dataclass(slots=True)
class MQTTConfig:
    host: str
    port: int = 1883
    keepalive_seconds: int = 60
    heartbeat_interval_seconds: int = 30
    username: str | None = None
    password: str | None = None
    tls: bool = False
    events_topic: str = "frigate/events"
    retain: bool = True
    qos: int = 1


@dataclass(slots=True)
class MQTTDiscoveryDeviceConfig:
    manufacturer: str = "Synthia"
    model: str = "Synthia Vision"
    sw_version: str = "0.1.0"


@dataclass(slots=True)
class MQTTDiscoveryConfig:
    enabled: bool = True
    prefix: str = "homeassistant"
    node_id: str = "synthia_vision"
    device: MQTTDiscoveryDeviceConfig = field(default_factory=MQTTDiscoveryDeviceConfig)


@dataclass(slots=True)
class FrigateSnapshotConfig:
    source: str = "event"
    endpoint_template: str = "/api/events/{event_id}/snapshot.jpg"
    timeout_seconds: int = 5
    max_bytes: int = 3_000_000
    retries: int = 3
    debug_save: bool = False
    retry_backoff_seconds: list[float] = field(default_factory=lambda: [0.3, 0.8, 1.5])


@dataclass(slots=True)
class FrigateConfig:
    base_url: str
    snapshot: FrigateSnapshotConfig
    stats_poll_seconds: int = 30


@dataclass(slots=True)
class OpenAIConfig:
    api_key: str
    model: str = "gpt-4o-mini"
    timeout_seconds: int = 20
    max_output_tokens: int = 200
    retry_attempts: int = 3
    retry_backoff_seconds: list[float] = field(default_factory=lambda: [0.5, 1.0, 2.0])


@dataclass(slots=True)
class AISetupOpenAIConfig:
    model: str = "gpt-4o-mini"
    max_output_tokens: int = 350
    timeout_seconds: int = 30


@dataclass(slots=True)
class AISetupStructuredOutputConfig:
    mode: str = "json_schema"
    schema_name: str = "camera_setup_context_v1"
    schema: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AISetupPromptsConfig:
    system: str = ""
    user: str = ""
    privacy_rules: str = ""


@dataclass(slots=True)
class AISetupConfig:
    openai: AISetupOpenAIConfig = field(default_factory=lambda: AISetupOpenAIConfig())
    structured_output: AISetupStructuredOutputConfig = field(
        default_factory=lambda: AISetupStructuredOutputConfig()
    )
    prompts: AISetupPromptsConfig = field(default_factory=lambda: AISetupPromptsConfig())


@dataclass(slots=True)
class AIProximityOverrideConfig:
    enabled: bool = False
    area_ratio_threshold: float = 0.25
    right_edge_touch_ratio: float = 0.95
    min_edge_touch_area_ratio: float = 0.05


@dataclass(slots=True)
class AIConfig:
    provider: str = "openai"
    openai: OpenAIConfig | None = None
    structured_output_mode: str = "json_schema"
    schema_name: str = "synthia_vision_event"
    schema: dict[str, Any] | None = None
    system_prompt: str = ""
    privacy_rules: str = ""
    security_overlay_template: str = ""
    per_camera_prompts: dict[str, str] | None = None
    default_prompt_preset: str = "outdoor"
    prompt_presets: dict[str, dict[str, str]] = field(default_factory=dict)
    include_expected_activity: bool = False
    debug_reasoning: bool = False
    vision_detail: str = "low"
    image_preprocess: "AIImagePreprocessConfig" = field(default_factory=lambda: AIImagePreprocessConfig())
    proximity_override: AIProximityOverrideConfig = field(
        default_factory=lambda: AIProximityOverrideConfig()
    )
    setup: AISetupConfig = field(default_factory=lambda: AISetupConfig())


@dataclass(slots=True)
class AIImagePreprocessConfig:
    enabled: bool = True
    max_side_px: int = 512
    jpeg_quality: int = 75
    strip_metadata: bool = True


@dataclass(slots=True)
class PolicyDefaultsConfig:
    enabled: bool = True
    process_on: list[str] = field(default_factory=lambda: ["end"])
    min_process_interval_seconds: float = 30.0
    labels: list[str] = field(default_factory=lambda: ["person"])
    min_score: float = 0.0
    min_duration_seconds: float = 0.0
    require_zones: list[str] = field(default_factory=list)
    confidence_threshold: float = 0.75


@dataclass(slots=True)
class PolicyCameraConfig:
    name: str | None = None
    enabled: bool = True
    security_capable: bool = False
    security_mode: bool = False
    labels: list[str] = field(default_factory=lambda: ["person"])
    confidence_threshold: float = 0.75
    cooldown_seconds: int = 30
    allowed_actions: list[str] = field(default_factory=list)
    prompt_preset: str | None = None
    vision_detail: str | None = None
    max_side_px: int | None = None
    suppression_enabled: bool | None = None
    suppression_window_seconds: int | None = None


@dataclass(slots=True)
class PolicyActionsConfig:
    default_action: str = "unknown"
    allowed: list[str] = field(default_factory=lambda: ["unknown"])


@dataclass(slots=True)
class PolicySubjectTypesConfig:
    default: str = "unknown"
    allowed: list[str] = field(default_factory=lambda: ["unknown"])


@dataclass(slots=True)
class PolicyConfig:
    defaults: PolicyDefaultsConfig
    cameras: dict[str, PolicyCameraConfig]
    actions: PolicyActionsConfig
    subject_types: PolicySubjectTypesConfig


@dataclass(slots=True)
class ModeConfig:
    enabled: bool = False
    allowed_cameras: list[str] = field(default_factory=list)
    confidence_threshold_override: float | None = None


@dataclass(slots=True)
class IntentModeProfileConfig:
    confidence_threshold: float | None = None
    monthly_budget: float | None = None
    updates_per_event: int | None = None
    prompt_preset: str | None = None
    doorbell_only_mode: bool | None = None
    high_precision_mode: bool | None = None


@dataclass(slots=True)
class ModesConfig:
    doorbell_only_mode: ModeConfig
    high_precision_mode: ModeConfig
    intent_available: list[str] = field(
        default_factory=lambda: ["normal", "delivery_watch", "guest_expected", "high_alert"]
    )
    intent_default: str = "normal"
    intent_profiles: dict[str, IntentModeProfileConfig] = field(default_factory=dict)
    intent_camera_profiles: dict[str, dict[str, IntentModeProfileConfig]] = field(default_factory=dict)


@dataclass(slots=True)
class BudgetConfig:
    enabled: bool = True
    currency: str = "USD"
    monthly_budget_limit: float = 10.0
    behavior_when_exceeded: str = "block_openai"
    publish_status: bool = True


@dataclass(slots=True)
class DedupeConfig:
    recent_event_ids_max: int = 400
    per_camera_cooldown_default_seconds: int = 30
    ignore_event_types: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SuppressionConfig:
    enabled: bool = True
    window_seconds: int = 15
    max_suppressed_log: int = 200


@dataclass(slots=True)
class EmbeddingsConfig:
    enabled: bool = False
    model: str = "text-embedding-3-small"
    retention_days: int = 30
    retention_max_rows: int = 5000
    store_vectors: bool = False


@dataclass(slots=True)
class ServiceConfig:
    app: AppConfig
    logging: LoggingConfig
    logging_files: LoggingComponentFiles
    service: ServiceIdentityConfig
    paths: ServicePathsConfig
    mqtt: MQTTConfig
    mqtt_discovery: MQTTDiscoveryConfig
    frigate: FrigateConfig
    ai: AIConfig
    policy: PolicyConfig
    modes: ModesConfig
    budget: BudgetConfig
    dedupe: DedupeConfig
    suppression: SuppressionConfig
    embeddings: EmbeddingsConfig
    topics: dict[str, Any]

    @property
    def openai(self) -> OpenAIConfig:
        if self.ai.openai is None:
            raise ConfigError("ai.openai configuration is missing")
        return self.ai.openai

    @property
    def state_file(self) -> Path:
        return self.paths.state_file


def load_settings(config_path: str | Path | None = None) -> ServiceConfig:
    """Load configuration from YAML file with environment placeholder support."""
    path = Path(config_path or os.getenv("SYNTHIA_CONFIG", "config/config.yaml"))
    merged_data = _load_yaml_mapping_with_includes(path)
    resolved_data = _resolve_env_placeholders(merged_data)
    _validate_schema_version(resolved_data, path)

    service_data = _as_mapping(resolved_data.get("service", {}), "service")
    service_paths_data = _as_mapping(service_data.get("paths", {}), "service.paths")
    mqtt_data = _as_mapping(resolved_data.get("mqtt", {}), "mqtt")
    mqtt_subscribe_data = _as_mapping(mqtt_data.get("subscribe", {}), "mqtt.subscribe")
    mqtt_publish_data = _as_mapping(mqtt_data.get("publish", {}), "mqtt.publish")
    mqtt_discovery_data = _as_mapping(mqtt_data.get("discovery", {}), "mqtt.discovery")
    mqtt_discovery_device_data = _as_mapping(
        mqtt_discovery_data.get("device", {}), "mqtt.discovery.device"
    )
    frigate_data = _as_mapping(resolved_data.get("frigate", {}), "frigate")
    frigate_snapshot_data = _as_mapping(frigate_data.get("snapshot", {}), "frigate.snapshot")
    ai_data = _as_mapping(resolved_data.get("ai", {}), "ai")
    openai_data = _as_mapping(ai_data.get("openai", {}), "ai.openai")
    structured_output_data = _as_mapping(
        ai_data.get("structured_output", {}), "ai.structured_output"
    )
    prompts_data = _as_mapping(ai_data.get("prompts", {}), "ai.prompts")
    setup_data = _as_mapping(ai_data.get("setup", {}), "ai.setup")
    setup_openai_data = _as_mapping(setup_data.get("openai", {}), "ai.setup.openai")
    setup_structured_output_data = _as_mapping(
        setup_data.get("structured_output", {}),
        "ai.setup.structured_output",
    )
    setup_prompts_data = _as_mapping(setup_data.get("prompts", {}), "ai.setup.prompts")
    image_preprocess_data = _as_mapping(
        ai_data.get("image_preprocess", {}),
        "ai.image_preprocess",
    )
    proximity_override_data = _as_mapping(
        ai_data.get("proximity_override", {}),
        "ai.proximity_override",
    )
    policy_data = _as_mapping(resolved_data.get("policy", {}), "policy")
    policy_defaults_data = _as_mapping(policy_data.get("defaults", {}), "policy.defaults")
    policy_actions_data = _as_mapping(policy_data.get("actions", {}), "policy.actions")
    policy_subject_types_data = _as_mapping(
        policy_data.get("subject_types", {}), "policy.subject_types"
    )
    policy_cameras_data = _as_mapping(policy_data.get("cameras", {}), "policy.cameras")
    modes_data = _as_mapping(resolved_data.get("modes", {}), "modes")
    doorbell_only_mode_data = _as_mapping(
        modes_data.get("doorbell_only_mode", {}), "modes.doorbell_only_mode"
    )
    high_precision_mode_data = _as_mapping(
        modes_data.get("high_precision_mode", {}), "modes.high_precision_mode"
    )
    high_precision_overrides_data = _as_mapping(
        high_precision_mode_data.get("overrides", {}), "modes.high_precision_mode.overrides"
    )
    intent_mode_data = _as_mapping(
        modes_data.get("intent", {}), "modes.intent"
    )
    intent_profiles_data = _as_mapping(
        intent_mode_data.get("profiles", {}), "modes.intent.profiles"
    )
    intent_camera_profiles_data = _as_mapping(
        intent_mode_data.get("camera_profiles", {}), "modes.intent.camera_profiles"
    )
    budget_data = _as_mapping(resolved_data.get("budget", {}), "budget")
    dedupe_data = _as_mapping(resolved_data.get("dedupe", {}), "dedupe")
    suppression_data = _as_mapping(resolved_data.get("suppression", {}), "suppression")
    embeddings_data = _as_mapping(resolved_data.get("embeddings", {}), "embeddings")
    topics_data = _as_mapping(resolved_data.get("topics", {}), "topics")
    logging_data = _as_mapping(resolved_data.get("logging", {}), "logging")
    logging_components_data = _as_mapping(
        logging_data.get("components", {}),
        "logging.components",
    )
    logging_files_data = _as_mapping(
        logging_data.get("files", {}),
        "logging.files",
    )
    default_level = str(logging_data.get("level", "INFO"))

    config = ServiceConfig(
        app=AppConfig(log_level=default_level),
        logging=LoggingConfig(
            level=default_level,
            file=_optional_str(logging_data.get("file")),
            json=_as_bool(logging_data.get("json", False)),
            retention_days=int(logging_data.get("retention_days", 14)),
            components=LoggingComponentLevels(
                core=str(logging_components_data.get("core", default_level)),
                mqtt=str(logging_components_data.get("mqtt", default_level)),
                config=str(logging_components_data.get("config", default_level)),
                policy=str(logging_components_data.get("policy", default_level)),
                ai=str(logging_components_data.get("ai", default_level)),
            ),
        ),
        logging_files=LoggingComponentFiles(
            core=_optional_str(logging_files_data.get("core")),
            mqtt=_optional_str(logging_files_data.get("mqtt")),
            config=_optional_str(logging_files_data.get("config")),
            policy=_optional_str(logging_files_data.get("policy")),
            ai=_optional_str(logging_files_data.get("ai")),
        ),
        service=ServiceIdentityConfig(
            name=str(service_data.get("name", "Synthia Vision")),
            slug=str(service_data.get("slug", "synthia_vision")),
            mqtt_prefix=str(service_data.get("mqtt_prefix", "home/synthiavision")),
        ),
        paths=ServicePathsConfig(
            state_file=Path(str(service_paths_data.get("state_file", "state/state.json"))),
            config_file=Path(str(service_paths_data.get("config_file", path))),
            snapshots_dir=Path(
                str(service_paths_data.get("snapshots_dir", "state/snapshots"))
            ),
            db_file=Path(
                str(service_paths_data.get("db_file", "state/synthia_vision.db"))
            ),
        ),
        mqtt=MQTTConfig(
            host=_required_str(mqtt_data.get("host"), "mqtt.host"),
            port=int(mqtt_data.get("port", 1883)),
            keepalive_seconds=int(mqtt_data.get("keepalive_seconds", 60)),
            heartbeat_interval_seconds=int(mqtt_data.get("heartbeat_interval_seconds", 30)),
            username=_optional_str(mqtt_data.get("username")),
            password=_optional_str(mqtt_data.get("password")),
            tls=_as_bool(mqtt_data.get("tls", False)),
            events_topic=str(
                mqtt_subscribe_data.get("frigate_events_topic", "frigate/events")
            ),
            retain=_as_bool(mqtt_publish_data.get("retain", True)),
            qos=int(mqtt_publish_data.get("qos", 1)),
        ),
        mqtt_discovery=MQTTDiscoveryConfig(
            enabled=_as_bool(mqtt_discovery_data.get("enabled", True)),
            prefix=str(mqtt_discovery_data.get("prefix", "homeassistant")),
            node_id=str(mqtt_discovery_data.get("node_id", "synthia_vision")),
            device=MQTTDiscoveryDeviceConfig(
                manufacturer=str(mqtt_discovery_device_data.get("manufacturer", "Synthia")),
                model=str(mqtt_discovery_device_data.get("model", "Synthia Vision")),
                sw_version=str(mqtt_discovery_device_data.get("sw_version", "0.1.0")),
            ),
        ),
        frigate=FrigateConfig(
            base_url=_required_str(frigate_data.get("api_base_url"), "frigate.api_base_url"),
            stats_poll_seconds=int(frigate_data.get("stats_poll_s", 30)),
            snapshot=FrigateSnapshotConfig(
                source=str(frigate_snapshot_data.get("source", "event")),
                endpoint_template=str(
                    frigate_snapshot_data.get(
                        "endpoint_template", "/api/events/{event_id}/snapshot.jpg"
                    )
                ),
                timeout_seconds=int(frigate_snapshot_data.get("timeout_s", 5)),
                max_bytes=int(frigate_snapshot_data.get("max_bytes", 3_000_000)),
                retries=int(frigate_snapshot_data.get("retries", 3)),
                debug_save=_as_bool(frigate_snapshot_data.get("debug_save", False)),
                retry_backoff_seconds=_as_float_list(
                    frigate_snapshot_data.get("retry_backoff_s", [0.3, 0.8, 1.5]),
                    "frigate.snapshot.retry_backoff_s",
                ),
            ),
        ),
        ai=AIConfig(
            provider=str(ai_data.get("provider", "openai")),
            openai=OpenAIConfig(
                api_key=_required_str(openai_data.get("api_key"), "ai.openai.api_key"),
                model=str(openai_data.get("model", "gpt-4o-mini")),
                timeout_seconds=int(openai_data.get("timeout_s", 20)),
                max_output_tokens=int(openai_data.get("max_output_tokens", 200)),
                retry_attempts=int(openai_data.get("retry_attempts", 3)),
                retry_backoff_seconds=_as_float_list(
                    openai_data.get("retry_backoff_s", [0.5, 1.0, 2.0]),
                    "ai.openai.retry_backoff_s",
                ),
            ),
            structured_output_mode=str(structured_output_data.get("mode", "json_schema")),
            schema_name=str(structured_output_data.get("schema_name", "synthia_vision_event")),
            schema=_as_mapping(
                structured_output_data.get("schema", {}),
                "ai.structured_output.schema",
            ),
            system_prompt=str(prompts_data.get("system", "")),
            privacy_rules=str(prompts_data.get("privacy_rules", "")),
            security_overlay_template=str(prompts_data.get("security_overlay_template", "")),
            per_camera_prompts=_as_mapping(
                prompts_data.get("per_camera", {}),
                "ai.prompts.per_camera",
            ),
            default_prompt_preset=str(prompts_data.get("default_preset", "outdoor")),
            prompt_presets=_build_prompt_presets(
                _as_mapping(prompts_data.get("presets", {}), "ai.prompts.presets")
            ),
            include_expected_activity=_as_bool(ai_data.get("include_expected_activity", False)),
            debug_reasoning=_as_bool(ai_data.get("debug_reasoning", False)),
            vision_detail=str(ai_data.get("vision_detail", "low")).lower(),
            image_preprocess=AIImagePreprocessConfig(
                enabled=_as_bool(image_preprocess_data.get("enabled", True)),
                max_side_px=int(image_preprocess_data.get("max_side_px", 512)),
                jpeg_quality=int(image_preprocess_data.get("jpeg_quality", 75)),
                strip_metadata=_as_bool(image_preprocess_data.get("strip_metadata", True)),
            ),
            proximity_override=AIProximityOverrideConfig(
                enabled=_as_bool(proximity_override_data.get("enabled", False)),
                area_ratio_threshold=float(
                    proximity_override_data.get("area_ratio_threshold", 0.25)
                ),
                right_edge_touch_ratio=float(
                    proximity_override_data.get("right_edge_touch_ratio", 0.95)
                ),
                min_edge_touch_area_ratio=float(
                    proximity_override_data.get("min_edge_touch_area_ratio", 0.05)
                ),
            ),
            setup=AISetupConfig(
                openai=AISetupOpenAIConfig(
                    model=str(setup_openai_data.get("model", "gpt-4o-mini")),
                    max_output_tokens=int(setup_openai_data.get("max_output_tokens", 350)),
                    timeout_seconds=int(setup_openai_data.get("timeout_s", 30)),
                ),
                structured_output=AISetupStructuredOutputConfig(
                    mode=str(setup_structured_output_data.get("mode", "json_schema")),
                    schema_name=str(
                        setup_structured_output_data.get(
                            "schema_name",
                            "camera_setup_context_v1",
                        )
                    ),
                    schema=_as_mapping(
                        setup_structured_output_data.get("schema", {}),
                        "ai.setup.structured_output.schema",
                    ),
                ),
                prompts=AISetupPromptsConfig(
                    system=str(setup_prompts_data.get("system", "")),
                    user=str(setup_prompts_data.get("user", "")),
                    privacy_rules=str(setup_prompts_data.get("privacy_rules", "")),
                ),
            ),
        ),
        policy=PolicyConfig(
            defaults=PolicyDefaultsConfig(
                enabled=_as_bool(policy_defaults_data.get("enabled", True)),
                process_on=_as_string_or_list(
                    policy_defaults_data.get("process_on", ["end"]),
                    "policy.defaults.process_on",
                ),
                min_process_interval_seconds=float(
                    policy_defaults_data.get("min_process_interval_s", 30.0)
                ),
                labels=_as_string_list(
                    policy_defaults_data.get("labels", ["person"]),
                    "policy.defaults.labels",
                ),
                min_score=float(policy_defaults_data.get("min_score", 0.0)),
                min_duration_seconds=float(
                    policy_defaults_data.get("min_duration_s", 0.0)
                ),
                require_zones=_as_string_list(
                    policy_defaults_data.get("require_zones", []),
                    "policy.defaults.require_zones",
                ),
                confidence_threshold=float(
                    policy_defaults_data.get("confidence_threshold", 0.75)
                ),
            ),
            cameras=_build_camera_policy_map(policy_cameras_data),
            actions=PolicyActionsConfig(
                default_action=str(policy_actions_data.get("default_action", "unknown")),
                allowed=_as_string_list(
                    policy_actions_data.get("allowed", ["unknown"]),
                    "policy.actions.allowed",
                ),
            ),
            subject_types=PolicySubjectTypesConfig(
                default=str(policy_subject_types_data.get("default", "unknown")),
                allowed=_as_string_list(
                    policy_subject_types_data.get("allowed", ["unknown"]),
                    "policy.subject_types.allowed",
                ),
            ),
        ),
        modes=ModesConfig(
            doorbell_only_mode=ModeConfig(
                enabled=_as_bool(doorbell_only_mode_data.get("enabled", True)),
                allowed_cameras=_as_string_list(
                    doorbell_only_mode_data.get("allowed_cameras", []),
                    "modes.doorbell_only_mode.allowed_cameras",
                ),
            ),
            high_precision_mode=ModeConfig(
                enabled=_as_bool(high_precision_mode_data.get("enabled", False)),
                confidence_threshold_override=_optional_float(
                    high_precision_overrides_data.get("confidence_threshold")
                ),
            ),
            intent_available=_as_string_list(
                intent_mode_data.get(
                    "available",
                    ["normal", "delivery_watch", "guest_expected", "high_alert"],
                ),
                "modes.intent.available",
            ),
            intent_default=str(intent_mode_data.get("default", "normal")).strip() or "normal",
            intent_profiles=_build_intent_mode_profiles(
                intent_profiles_data,
                "modes.intent.profiles",
            ),
            intent_camera_profiles=_build_intent_camera_profiles(
                intent_camera_profiles_data,
                "modes.intent.camera_profiles",
            ),
        ),
        budget=BudgetConfig(
            enabled=_as_bool(budget_data.get("enabled", True)),
            currency=str(budget_data.get("currency", "USD")),
            monthly_budget_limit=float(budget_data.get("monthly_limit", 10.0)),
            behavior_when_exceeded=str(
                budget_data.get("behavior_when_exceeded", "block_openai")
            ),
            publish_status=_as_bool(budget_data.get("publish_status", True)),
        ),
        dedupe=DedupeConfig(
            recent_event_ids_max=int(dedupe_data.get("recent_event_ids_max", 400)),
            per_camera_cooldown_default_seconds=int(
                dedupe_data.get("per_camera_cooldown_default_s", 30)
            ),
            ignore_event_types=_as_string_list(
                dedupe_data.get("ignore_event_types", []),
                "dedupe.ignore_event_types",
            ),
        ),
        suppression=SuppressionConfig(
            enabled=_as_bool(suppression_data.get("enabled", True)),
            window_seconds=max(0, int(suppression_data.get("window_seconds", 15))),
            max_suppressed_log=max(0, int(suppression_data.get("max_suppressed_log", 200))),
        ),
        embeddings=EmbeddingsConfig(
            enabled=_as_bool(embeddings_data.get("enabled", False)),
            model=str(embeddings_data.get("model", "text-embedding-3-small")),
            retention_days=max(1, int(embeddings_data.get("retention_days", 30))),
            retention_max_rows=max(1, int(embeddings_data.get("retention_max_rows", 5000))),
            store_vectors=_as_bool(embeddings_data.get("store_vectors", False)),
        ),
        topics=topics_data,
    )

    _apply_env_overrides(config)
    _validate_config(config)
    LOGGER.debug(
        "Loaded configuration file=%s mqtt_host=%s mqtt_topic=%s",
        path,
        config.mqtt.host,
        config.mqtt.events_topic,
    )
    return config


def _build_camera_policy_map(data: dict[str, Any]) -> dict[str, PolicyCameraConfig]:
    cameras: dict[str, PolicyCameraConfig] = {}
    for camera_name, raw_value in data.items():
        if not isinstance(raw_value, dict):
            raise ConfigError(f"Expected mapping for policy.cameras.{camera_name}")
        actions_data = _as_mapping(
            raw_value.get("actions", {}), f"policy.cameras.{camera_name}.actions"
        )
        cameras[camera_name] = PolicyCameraConfig(
            name=_optional_str(raw_value.get("name")),
            enabled=_as_bool(raw_value.get("enabled", True)),
            security_capable=_as_bool(raw_value.get("security_capable", False)),
            security_mode=_as_bool(raw_value.get("security_mode", False)),
            labels=_as_string_list(
                raw_value.get("labels", ["person"]),
                f"policy.cameras.{camera_name}.labels",
            ),
            confidence_threshold=float(raw_value.get("confidence_threshold", 0.75)),
            cooldown_seconds=int(raw_value.get("cooldown_s", 30)),
            prompt_preset=_optional_str(raw_value.get("prompt_preset")),
            vision_detail=_optional_str(raw_value.get("vision_detail")),
            max_side_px=_optional_int(raw_value.get("max_side_px")),
            suppression_enabled=_optional_bool(raw_value.get("suppression_enabled")),
            suppression_window_seconds=_optional_int(raw_value.get("suppression_window_seconds")),
            allowed_actions=_as_string_list(
                actions_data.get("allowed", []),
                f"policy.cameras.{camera_name}.actions.allowed",
            ),
        )
    return cameras


def _build_prompt_presets(data: dict[str, Any]) -> dict[str, dict[str, str]]:
    presets: dict[str, dict[str, str]] = {}
    for preset_name, raw_value in data.items():
        if not isinstance(raw_value, dict):
            raise ConfigError(f"Expected mapping at: ai.prompts.presets.{preset_name}")
        presets[preset_name] = {
            "system": str(raw_value.get("system", "")),
            "user": str(raw_value.get("user", "")),
        }
    return presets


def _parse_intent_mode_profile(data: dict[str, Any]) -> IntentModeProfileConfig:
    updates_value = _optional_int(data.get("updates_per_event"))
    if updates_value is not None:
        updates_value = max(1, min(2, updates_value))
    return IntentModeProfileConfig(
        confidence_threshold=_optional_float(data.get("confidence_threshold")),
        monthly_budget=_optional_float(data.get("monthly_budget")),
        updates_per_event=updates_value,
        prompt_preset=_optional_str(data.get("prompt_preset")),
        doorbell_only_mode=_optional_bool(data.get("doorbell_only_mode")),
        high_precision_mode=_optional_bool(data.get("high_precision_mode")),
    )


def _build_intent_mode_profiles(
    data: dict[str, Any],
    field_name: str,
) -> dict[str, IntentModeProfileConfig]:
    profiles: dict[str, IntentModeProfileConfig] = {}
    for mode_name, raw_value in data.items():
        if not isinstance(raw_value, dict):
            raise ConfigError(f"Expected mapping at: {field_name}.{mode_name}")
        profiles[str(mode_name)] = _parse_intent_mode_profile(
            _as_mapping(raw_value, f"{field_name}.{mode_name}"),
        )
    return profiles


def _build_intent_camera_profiles(
    data: dict[str, Any],
    field_name: str,
) -> dict[str, dict[str, IntentModeProfileConfig]]:
    result: dict[str, dict[str, IntentModeProfileConfig]] = {}
    for camera_name, raw_camera in data.items():
        camera_mapping = _as_mapping(raw_camera, f"{field_name}.{camera_name}")
        mode_profiles: dict[str, IntentModeProfileConfig] = {}
        for mode_name, raw_mode in camera_mapping.items():
            if not isinstance(raw_mode, dict):
                raise ConfigError(
                    f"Expected mapping at: {field_name}.{camera_name}.{mode_name}"
                )
            mode_profiles[str(mode_name)] = _parse_intent_mode_profile(
                _as_mapping(
                    raw_mode,
                    f"{field_name}.{camera_name}.{mode_name}",
                ),
            )
        result[str(camera_name)] = mode_profiles
    return result


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Configuration file not found: {path}")
    try:
        import yaml
    except ImportError as exc:
        raise ConfigError("PyYAML is required to load config/config.yaml") from exc

    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
    except Exception as exc:
        raise ConfigError(f"Failed to read configuration file {path}: {exc}") from exc

    if not isinstance(loaded, dict):
        raise ConfigError(f"Configuration root must be a mapping: {path}")
    return loaded


def _load_yaml_mapping_with_includes(path: Path) -> dict[str, Any]:
    root = _load_yaml_mapping(path)
    includes = root.get("includes", [])
    if not isinstance(includes, list):
        raise ConfigError("Expected list at: includes")
    merged = dict(root)
    merged.pop("includes", None)
    for include_path in _expand_include_paths(path.parent, includes):
        include_data = _load_yaml_mapping(include_path)
        merged = _deep_merge_mappings(merged, include_data)
    return merged


def _expand_include_paths(base_dir: Path, includes: list[Any]) -> list[Path]:
    expanded: list[Path] = []
    for include in includes:
        if not isinstance(include, str) or not include.strip():
            raise ConfigError("All includes entries must be non-empty strings")
        raw = include.strip()
        # Support explicit file paths and glob patterns like config.d/*.yaml.
        if any(token in raw for token in ("*", "?", "[")):
            matches = sorted((base_dir / ".").glob(raw))
            if not matches:
                raise ConfigError(f"Config include glob matched no files: {raw}")
            expanded.extend(path for path in matches if path.is_file())
            continue
        include_path = (base_dir / raw).resolve()
        if not include_path.exists():
            raise ConfigError(f"Config include not found: {raw}")
        if not include_path.is_file():
            raise ConfigError(f"Config include is not a file: {raw}")
        expanded.append(include_path)
    return expanded


def _deep_merge_mappings(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge_mappings(merged[key], value)
            continue
        # Lists are replaced by design (not concatenated) for predictable overrides.
        merged[key] = value
    return merged


def _validate_schema_version(data: dict[str, Any], config_path: Path) -> None:
    raw = data.get("schema_version")
    if not isinstance(raw, int):
        raise ConfigError(
            f"Config schema_version is required and must be an integer in {config_path}"
        )
    if raw != SUPPORTED_CONFIG_SCHEMA_VERSION:
        raise ConfigError(
            "Unsupported config schema_version="
            f"{raw}; expected {SUPPORTED_CONFIG_SCHEMA_VERSION}"
        )


def _resolve_env_placeholders(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _resolve_env_placeholders(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_env_placeholders(item) for item in value]
    if isinstance(value, str):
        match = ENV_PLACEHOLDER_PATTERN.match(value.strip())
        if match:
            env_name = match.group(1)
            return os.getenv(env_name, "")
    return value


def _apply_env_overrides(config: ServiceConfig) -> None:
    config.openai.api_key = os.getenv("OPENAI_API_KEY", config.openai.api_key)
    config.mqtt.password = os.getenv("MQTT_PASSWORD", config.mqtt.password)
    config.mqtt.username = os.getenv("MQTT_USERNAME", config.mqtt.username)
    config.mqtt.host = os.getenv("MQTT_HOST", config.mqtt.host)
    if "MQTT_PORT" in os.environ:
        config.mqtt.port = int(os.environ["MQTT_PORT"])
    if "MQTT_KEEPALIVE_SECONDS" in os.environ:
        config.mqtt.keepalive_seconds = int(os.environ["MQTT_KEEPALIVE_SECONDS"])
    if "MQTT_HEARTBEAT_SECONDS" in os.environ:
        config.mqtt.heartbeat_interval_seconds = int(os.environ["MQTT_HEARTBEAT_SECONDS"])
    config.frigate.base_url = os.getenv("FRIGATE_BASE_URL", config.frigate.base_url)
    if "FRIGATE_STATS_POLL_S" in os.environ:
        config.frigate.stats_poll_seconds = int(os.environ["FRIGATE_STATS_POLL_S"])
    config.openai.model = os.getenv("OPENAI_MODEL", config.openai.model)
    config.app.log_level = os.getenv("SYNTHIA_LOG_LEVEL", config.app.log_level)
    config.logging.level = config.app.log_level
    if "SYNTHIA_LOG_CORE" in os.environ:
        config.logging.components.core = os.environ["SYNTHIA_LOG_CORE"]
    if "SYNTHIA_LOG_MQTT" in os.environ:
        config.logging.components.mqtt = os.environ["SYNTHIA_LOG_MQTT"]
    if "SYNTHIA_LOG_CONFIG" in os.environ:
        config.logging.components.config = os.environ["SYNTHIA_LOG_CONFIG"]
    if "SYNTHIA_LOG_POLICY" in os.environ:
        config.logging.components.policy = os.environ["SYNTHIA_LOG_POLICY"]
    if "SYNTHIA_LOG_AI" in os.environ:
        config.logging.components.ai = os.environ["SYNTHIA_LOG_AI"]
    if "SYNTHIA_LOG_RETENTION_DAYS" in os.environ:
        config.logging.retention_days = int(os.environ["SYNTHIA_LOG_RETENTION_DAYS"])

    if "SYNTHIA_MONTHLY_BUDGET_LIMIT" in os.environ:
        config.budget.monthly_budget_limit = float(
            os.environ["SYNTHIA_MONTHLY_BUDGET_LIMIT"]
        )
    if "SYNTHIA_CONFIDENCE_THRESHOLD" in os.environ:
        config.policy.defaults.confidence_threshold = float(
            os.environ["SYNTHIA_CONFIDENCE_THRESHOLD"]
        )


def _validate_config(config: ServiceConfig) -> None:
    if config.logging.retention_days < 1:
        raise ConfigError("logging.retention_days must be >= 1")
    if config.policy.defaults.min_process_interval_seconds < 0:
        raise ConfigError("policy.defaults.min_process_interval_s must be >= 0")
    _validate_threshold(config.policy.defaults.confidence_threshold)
    for camera_name, camera_policy in config.policy.cameras.items():
        try:
            _validate_threshold(camera_policy.confidence_threshold)
        except ConfigError as exc:
            raise ConfigError(f"Invalid confidence for camera '{camera_name}': {exc}") from exc

    if config.budget.monthly_budget_limit < 0:
        raise ConfigError("budget.monthly_limit must be >= 0")
    if config.mqtt.qos not in (0, 1, 2):
        raise ConfigError("mqtt.publish.qos must be 0, 1, or 2")
    if config.frigate.stats_poll_seconds < 5:
        raise ConfigError("frigate.stats_poll_s must be >= 5")
    if config.suppression.window_seconds < 0:
        raise ConfigError("suppression.window_seconds must be >= 0")
    if config.suppression.max_suppressed_log < 0:
        raise ConfigError("suppression.max_suppressed_log must be >= 0")
    if not str(config.embeddings.model).strip():
        raise ConfigError("embeddings.model must not be empty")
    if config.embeddings.retention_days < 1:
        raise ConfigError("embeddings.retention_days must be >= 1")
    if config.embeddings.retention_max_rows < 1:
        raise ConfigError("embeddings.retention_max_rows must be >= 1")
    if not config.modes.intent_available:
        raise ConfigError("modes.intent.available must not be empty")
    if config.modes.intent_default not in set(config.modes.intent_available):
        raise ConfigError("modes.intent.default must be included in modes.intent.available")
    for mode_name, profile in config.modes.intent_profiles.items():
        if mode_name not in set(config.modes.intent_available):
            raise ConfigError(
                f"modes.intent.profiles.{mode_name} must exist in modes.intent.available"
            )
        if profile.confidence_threshold is not None:
            _validate_threshold(profile.confidence_threshold)
        if profile.monthly_budget is not None and profile.monthly_budget < 0:
            raise ConfigError(f"modes.intent.profiles.{mode_name}.monthly_budget must be >= 0")
    for camera_name, camera_profiles in config.modes.intent_camera_profiles.items():
        for mode_name, profile in camera_profiles.items():
            if mode_name not in set(config.modes.intent_available):
                raise ConfigError(
                    f"modes.intent.camera_profiles.{camera_name}.{mode_name} must exist in modes.intent.available"
                )
            if profile.confidence_threshold is not None:
                _validate_threshold(profile.confidence_threshold)
            if profile.monthly_budget is not None and profile.monthly_budget < 0:
                raise ConfigError(
                    f"modes.intent.camera_profiles.{camera_name}.{mode_name}.monthly_budget must be >= 0"
                )

    if not config.openai.api_key:
        raise ConfigError(
            "Missing OpenAI API key. Set ai.openai.api_key or OPENAI_API_KEY."
        )
    if config.openai.retry_attempts < 1:
        raise ConfigError("ai.openai.retry_attempts must be >= 1")
    if config.ai.vision_detail not in {"low", "high", "auto"}:
        raise ConfigError("ai.vision_detail must be one of: low, high, auto")
    if config.ai.image_preprocess.max_side_px < 128:
        raise ConfigError("ai.image_preprocess.max_side_px must be >= 128")
    if config.ai.image_preprocess.jpeg_quality < 40 or config.ai.image_preprocess.jpeg_quality > 95:
        raise ConfigError("ai.image_preprocess.jpeg_quality must be between 40 and 95")
    if config.ai.proximity_override.area_ratio_threshold <= 0 or config.ai.proximity_override.area_ratio_threshold > 1:
        raise ConfigError("ai.proximity_override.area_ratio_threshold must be > 0 and <= 1")
    if (
        config.ai.proximity_override.right_edge_touch_ratio < 0
        or config.ai.proximity_override.right_edge_touch_ratio > 1
    ):
        raise ConfigError("ai.proximity_override.right_edge_touch_ratio must be between 0 and 1")
    if (
        config.ai.proximity_override.min_edge_touch_area_ratio <= 0
        or config.ai.proximity_override.min_edge_touch_area_ratio > 1
    ):
        raise ConfigError("ai.proximity_override.min_edge_touch_area_ratio must be > 0 and <= 1")
    if config.ai.setup.structured_output.mode != "json_schema":
        raise ConfigError("ai.setup.structured_output.mode must be json_schema")
    if not config.ai.setup.structured_output.schema:
        raise ConfigError("ai.setup.structured_output.schema must not be empty")
    if config.policy.actions.default_action not in set(config.policy.actions.allowed):
        raise ConfigError("policy.actions.default_action must be included in policy.actions.allowed")
    if config.policy.subject_types.default not in set(config.policy.subject_types.allowed):
        raise ConfigError(
            "policy.subject_types.default must be included in policy.subject_types.allowed"
        )
    if not config.policy.actions.allowed:
        raise ConfigError("policy.actions.allowed must not be empty")
    if not config.policy.subject_types.allowed:
        raise ConfigError("policy.subject_types.allowed must not be empty")
    if (
        config.ai.prompt_presets
        and config.ai.default_prompt_preset not in set(config.ai.prompt_presets.keys())
    ):
        raise ConfigError("ai.prompts.default_preset must exist in ai.prompts.presets")
    allowed_action_set = set(config.policy.actions.allowed)
    for camera_name, camera_policy in config.policy.cameras.items():
        if camera_policy.vision_detail and camera_policy.vision_detail not in {"low", "high", "auto"}:
            raise ConfigError(
                f"policy.cameras.{camera_name}.vision_detail must be one of: low, high, auto"
            )
        if camera_policy.max_side_px is not None and camera_policy.max_side_px < 128:
            raise ConfigError(f"policy.cameras.{camera_name}.max_side_px must be >= 128")
        if (
            camera_policy.suppression_window_seconds is not None
            and camera_policy.suppression_window_seconds < 0
        ):
            raise ConfigError(
                f"policy.cameras.{camera_name}.suppression_window_seconds must be >= 0"
            )
        if camera_policy.allowed_actions:
            invalid_actions = [
                action for action in camera_policy.allowed_actions if action not in allowed_action_set
            ]
            if invalid_actions:
                raise ConfigError(
                    f"policy.cameras.{camera_name}.actions.allowed contains invalid values: {invalid_actions}"
                )


def _required_str(value: Any, field_name: str) -> str:
    if isinstance(value, str) and value:
        return value
    raise ConfigError(f"Missing required config value: {field_name}")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        if value.strip() == "":
            return None
        return value
    raise ConfigError("Expected optional string value")


def _as_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    raise ConfigError(f"Expected mapping at: {field_name}")


def _as_string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ConfigError(f"Expected list at: {field_name}")
    if not all(isinstance(item, str) for item in value):
        raise ConfigError(f"Expected string list at: {field_name}")
    return value


def _as_string_or_list(value: Any, field_name: str) -> list[str]:
    if isinstance(value, str):
        return [value]
    return _as_string_list(value, field_name)


def _as_float_list(value: Any, field_name: str) -> list[float]:
    if not isinstance(value, list):
        raise ConfigError(f"Expected list at: {field_name}")
    result: list[float] = []
    for item in value:
        if not isinstance(item, (int, float)):
            raise ConfigError(f"Expected numeric list at: {field_name}")
        result.append(float(item))
    return result


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ConfigError(f"Expected boolean value, got {type(value).__name__}")


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ConfigError("Expected optional bool value")


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raise ConfigError("Expected optional numeric value")


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ConfigError("Expected optional integer value")


def _validate_threshold(value: float) -> None:
    if value < 0.0 or value > 1.0:
        raise ConfigError("confidence_threshold must be between 0 and 1")
