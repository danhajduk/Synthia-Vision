"""Pydantic models for camera setup profile/view APIs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class CameraProfile(BaseModel):
    camera_key: str
    environment: Literal["indoor", "outdoor"] | None = None
    purpose: str | None = None
    view_type: Literal["fixed", "wide", "ptz"] | None = None
    mounting_location: str | None = None
    view_notes: str | None = None
    delivery_focus: list[Literal["package", "food", "grocery"]] = Field(default_factory=list)
    privacy_mode: Literal["no_identifying_details"] = "no_identifying_details"
    setup_completed: bool = False
    default_view_id: str | None = None


class CameraView(BaseModel):
    camera_key: str
    view_id: str
    label: str
    ha_preset_id: str | None = None
    setup_snapshot_path: str | None = None
    context_summary: str | None = None
    expected_activity: list[str] = Field(default_factory=list)
    zones: list[dict[str, Any]] = Field(default_factory=list)
    focus_notes: str | None = None
    created_ts: int
    updated_ts: int


class CameraSetupGenerateRequest(BaseModel):
    environment: Literal["indoor", "outdoor"]
    purpose: str = Field(min_length=2, max_length=40)
    view_type: Literal["fixed", "wide", "ptz"]
    mounting_location: str | None = Field(default=None, max_length=80)
    view_notes: str | None = Field(default=None, max_length=300)
    delivery_focus: list[Literal["package", "food", "grocery"]] = Field(default_factory=list, max_length=3)


class CameraSetupGenerateResponse(BaseModel):
    schema_version: Literal[1] = 1
    environment: Literal["indoor", "outdoor"]
    purpose: str
    view_type: Literal["fixed", "wide", "ptz"]
    context_summary: str
    expected_activity: list[str]
    zones: list[dict[str, Any]] = Field(default_factory=list)
    focus_notes: str
    delivery_focus: list[Literal["package", "food", "grocery"]] = Field(default_factory=list)
    privacy_mode: Literal["no_identifying_details"] = "no_identifying_details"

