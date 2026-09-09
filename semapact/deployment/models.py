"""Provider-neutral immutable deployment planning artifacts."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from open_data_contract_standard.model import SchemaObject
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from semapact.lifecycle.identity import normalize_identity_name


class DeploymentModel(BaseModel):
    """Shared immutable base for deployment planning artifacts."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class DeploymentActionKind(str, Enum):
    """Provider-neutral convergence intents emitted by deployment planning."""

    ENSURE_ASSET_STATE = "ENSURE_ASSET_STATE"


class DeploymentTarget(DeploymentModel):
    """Explicit runtime target for one DeploymentPlan."""

    platform: str
    runtime_target: str
    server_name: str | None = None

    @field_validator("platform")
    @classmethod
    def _normalize_platform(cls, value: str) -> str:
        cleaned = value.strip().casefold()
        if not cleaned:
            raise ValueError("platform must not be empty")
        return cleaned

    @field_validator("runtime_target")
    @classmethod
    def _normalize_runtime_target(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("runtime_target must not be empty")
        return cleaned

    @field_validator("server_name")
    @classmethod
    def _normalize_server_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class DeploymentAction(DeploymentModel):
    """One machine-readable desired-state convergence intent."""

    kind: DeploymentActionKind
    governed_asset: str
    physical_name: str
    desired_state_json: str

    @field_validator("governed_asset", "physical_name", "desired_state_json")
    @classmethod
    def _require_non_empty_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned

    @model_validator(mode="after")
    def _validate_desired_state_identity(self) -> DeploymentAction:
        schema = SchemaObject.model_validate_json(self.desired_state_json)
        schema_name = getattr(schema, "name", None)
        if schema_name is None:
            raise ValueError("desired schema state must define name")
        governed_asset = normalize_identity_name(str(schema_name), "Schema")
        if governed_asset != self.governed_asset:
            raise ValueError(
                "desired schema state identity does not match governed_asset"
            )

        physical_value = getattr(schema, "physicalName", None)
        expected_physical = (
            str(physical_value).strip()
            if physical_value is not None and str(physical_value).strip()
            else str(schema_name).strip()
        )
        if expected_physical != self.physical_name:
            raise ValueError(
                "desired schema physicalName does not match deployment physical_name"
            )
        return self


class DeploymentPlan(DeploymentModel):
    """Pure deterministic runtime convergence plan for one applied release."""

    deployment_plan_id: str
    applied_release_id: str
    contract_id: str
    release_plan_id: str
    released_revision_ref: str
    selected_version: str
    target: DeploymentTarget
    actions: tuple[DeploymentAction, ...]
    plan_version: Literal["1"] = "1"

    @field_validator(
        "deployment_plan_id",
        "applied_release_id",
        "contract_id",
        "release_plan_id",
        "released_revision_ref",
        "selected_version",
    )
    @classmethod
    def _require_plan_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned

    @model_validator(mode="after")
    def _validate_action_order_and_identity(self) -> DeploymentPlan:
        governed_assets = [action.governed_asset for action in self.actions]
        if governed_assets != sorted(governed_assets):
            raise ValueError("DeploymentPlan actions must be ordered by governed_asset")
        if len(governed_assets) != len(set(governed_assets)):
            raise ValueError("DeploymentPlan cannot contain duplicate governed assets")
        return self
