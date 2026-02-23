"""Pydantic models for camera setup profile/view APIs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

PurposeType = Literal[
    "doorbell_entry",
    "perimeter_security",
    "driveway",
    "backyard",
    "garage",
    "indoor_general",
    "child_room",
    "other",
]

ViewType = Literal["fixed", "wide", "ptz"]
EnvironmentType = Literal["indoor", "outdoor"]
DeliveryFocusType = Literal["package", "food", "grocery"]


class CameraProfile(BaseModel):
    camera_key: str
    environment: EnvironmentType | None = None
    purpose: PurposeType | None = None
    view_type: ViewType | None = None
    mounting_location: str | None = Field(default=None, max_length=200)
    view_notes: str | None = Field(default=None, max_length=500)
    delivery_focus: list[DeliveryFocusType] = Field(default_factory=list, max_length=3)
    privacy_mode: Literal["no_identifying_details"] = "no_identifying_details"
    setup_completed: bool = False
    default_view_id: str | None = Field(default=None, max_length=40)


class CameraView(BaseModel):
    camera_key: str
    view_id: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=60)
    ha_preset_id: str | None = Field(default=None, max_length=80)
    setup_snapshot_path: str | None = None
    context_summary: str | None = Field(default=None, max_length=220)
    expected_activity: list[str] = Field(default_factory=list, max_length=10)
    zones: list[dict[str, Any]] = Field(default_factory=list)
    focus_notes: str | None = Field(default=None, max_length=260)
    created_ts: int
    updated_ts: int


class CameraSetupGenerateRequest(BaseModel):
    environment: EnvironmentType
    purpose: PurposeType
    view_type: ViewType
    mounting_location: str = Field(min_length=1, max_length=200)
    view_notes: str | None = Field(default=None, max_length=500)
    delivery_focus: list[DeliveryFocusType] = Field(default_factory=list, max_length=3)


class CameraSetupGenerateResponse(BaseModel):
    schema_version: Literal[1] = 1
    environment: EnvironmentType
    purpose: PurposeType
    view_type: ViewType
    context_summary: str = Field(min_length=10, max_length=220)
    expected_activity: list[str] = Field(default_factory=list, min_length=3, max_length=10)
    zones: list[dict[str, Any]] = Field(default_factory=list, max_length=6)
    focus_notes: str = Field(min_length=5, max_length=260)
    delivery_focus: list[DeliveryFocusType] = Field(default_factory=list, max_length=3)
    privacy_mode: Literal["no_identifying_details"] = "no_identifying_details"


class CameraViewUpsertRequest(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    ha_preset_id: str | None = Field(default=None, max_length=80)
    context_summary: str | None = Field(default=None, max_length=220)
    expected_activity: list[str] = Field(default_factory=list, max_length=10)
    zones: list[dict[str, Any]] = Field(default_factory=list, max_length=6)
    focus_notes: str | None = Field(default=None, max_length=260)
