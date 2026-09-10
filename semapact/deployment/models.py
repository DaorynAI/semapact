"""Provider-neutral immutable deployment planning, preview, and authorization artifacts."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Literal, Sequence

from open_data_contract_standard.model import SchemaObject
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from semapact.lifecycle.identity import normalize_identity_name
from semapact.utils.deterministic import deterministic_uuid5


SEMAPACT_DEPLOYMENT_PLAN_NAMESPACE = uuid.UUID(
    "d59eaa31-997a-478d-9978-4659beee673d"
)
SEMAPACT_DEPLOYMENT_AUTHORIZATION_NAMESPACE = uuid.UUID(
    "c1dd6b40-cb67-44c1-b0f2-5f133ba6a3f5"
)
SEMAPACT_DEPLOYMENT_PREVIEW_NAMESPACE = uuid.UUID(
    "0ee613b9-a9ef-4a95-ac87-25d6c706b16c"
)


class DeploymentModel(BaseModel):
    """Shared immutable base for deployment domain artifacts."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class DeploymentActionKind(str, Enum):
    """Provider-neutral convergence intents emitted by deployment planning."""

    ENSURE_ASSET_STATE = "ENSURE_ASSET_STATE"


class NativeOperationKind(str, Enum):
    """Provider-native operation classes derived from runtime evidence."""

    CREATE = "CREATE"
    ALTER = "ALTER"
    NO_OP = "NO_OP"


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
        validate_deployment_plan_identity(self)
        return self


class NativeOperation(DeploymentModel):
    """One immutable provider-native operation selected by an adapter preview."""

    kind: NativeOperationKind
    governed_asset: str
    statement: str | None = None

    @field_validator("governed_asset")
    @classmethod
    def _require_governed_asset(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("governed_asset must not be empty")
        return cleaned

    @model_validator(mode="after")
    def _validate_statement_shape(self) -> NativeOperation:
        if self.kind is NativeOperationKind.NO_OP:
            if self.statement is not None:
                raise ValueError("NO_OP must not carry a provider statement")
            return self
        if self.statement is None or not self.statement.strip():
            raise ValueError(f"{self.kind.value} requires a provider statement")
        return self


class DeploymentPreview(DeploymentModel):
    """Deterministic provider-native preview bound to one observed runtime state."""

    deployment_preview_id: str
    deployment_plan_id: str
    platform: str
    runtime_target: str
    source_identifier: str
    observation_fingerprint: str
    operations: tuple[NativeOperation, ...]
    preview_version: Literal["1"] = "1"

    @field_validator(
        "deployment_preview_id",
        "deployment_plan_id",
        "platform",
        "runtime_target",
        "source_identifier",
        "observation_fingerprint",
    )
    @classmethod
    def _require_preview_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("preview fields must not be empty")
        return cleaned

    @model_validator(mode="after")
    def _validate_identity(self) -> DeploymentPreview:
        validate_deployment_preview_identity(self)
        return self


class DeploymentAuthorization(DeploymentModel):
    """Authorization bound to one exact DeploymentPlan and applied release."""

    deployment_authorization_id: str
    contract_ops_authorization_id: str
    deployment_plan_id: str
    applied_release_id: str
    allowed: bool = Field(strict=True)

    @field_validator(
        "deployment_authorization_id",
        "contract_ops_authorization_id",
        "deployment_plan_id",
        "applied_release_id",
    )
    @classmethod
    def _require_authorization_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned

    @model_validator(mode="after")
    def _validate_identity(self) -> DeploymentAuthorization:
        validate_deployment_authorization_identity(self)
        return self


def compute_deployment_plan_id(
    *,
    applied_release_id: str,
    contract_id: str,
    release_plan_id: str,
    released_revision_ref: str,
    selected_version: str,
    target: DeploymentTarget,
    actions: Sequence[DeploymentAction],
    plan_version: str = "1",
) -> str:
    return deterministic_uuid5(
        SEMAPACT_DEPLOYMENT_PLAN_NAMESPACE,
        {
            "applied_release_id": applied_release_id,
            "contract_id": contract_id,
            "release_plan_id": release_plan_id,
            "released_revision_ref": released_revision_ref,
            "selected_version": selected_version,
            "target": target.model_dump(mode="json"),
            "actions": [action.model_dump(mode="json") for action in actions],
            "plan_version": plan_version,
        },
    )


def compute_deployment_authorization_id(
    *,
    contract_ops_authorization_id: str,
    deployment_plan_id: str,
    applied_release_id: str,
    allowed: bool,
) -> str:
    return deterministic_uuid5(
        SEMAPACT_DEPLOYMENT_AUTHORIZATION_NAMESPACE,
        {
            "contract_ops_authorization_id": contract_ops_authorization_id,
            "deployment_plan_id": deployment_plan_id,
            "applied_release_id": applied_release_id,
            "allowed": allowed,
        },
    )


def compute_deployment_preview_id(
    *,
    deployment_plan_id: str,
    platform: str,
    runtime_target: str,
    source_identifier: str,
    observation_fingerprint: str,
    operations: Sequence[NativeOperation],
    preview_version: str = "1",
) -> str:
    return deterministic_uuid5(
        SEMAPACT_DEPLOYMENT_PREVIEW_NAMESPACE,
        {
            "deployment_plan_id": deployment_plan_id,
            "platform": platform,
            "runtime_target": runtime_target,
            "source_identifier": source_identifier,
            "observation_fingerprint": observation_fingerprint,
            "operations": [operation.model_dump(mode="json") for operation in operations],
            "preview_version": preview_version,
        },
    )


def validate_deployment_plan_identity(plan: DeploymentPlan) -> None:
    expected = compute_deployment_plan_id(
        applied_release_id=plan.applied_release_id,
        contract_id=plan.contract_id,
        release_plan_id=plan.release_plan_id,
        released_revision_ref=plan.released_revision_ref,
        selected_version=plan.selected_version,
        target=plan.target,
        actions=plan.actions,
        plan_version=plan.plan_version,
    )
    if expected != plan.deployment_plan_id:
        raise ValueError("DeploymentPlan deterministic identity does not match content")


def validate_deployment_authorization_identity(
    authorization: DeploymentAuthorization,
) -> None:
    expected = compute_deployment_authorization_id(
        contract_ops_authorization_id=authorization.contract_ops_authorization_id,
        deployment_plan_id=authorization.deployment_plan_id,
        applied_release_id=authorization.applied_release_id,
        allowed=authorization.allowed,
    )
    if expected != authorization.deployment_authorization_id:
        raise ValueError(
            "DeploymentAuthorization deterministic identity does not match content"
        )


def validate_deployment_preview_identity(preview: DeploymentPreview) -> None:
    expected = compute_deployment_preview_id(
        deployment_plan_id=preview.deployment_plan_id,
        platform=preview.platform,
        runtime_target=preview.runtime_target,
        source_identifier=preview.source_identifier,
        observation_fingerprint=preview.observation_fingerprint,
        operations=preview.operations,
        preview_version=preview.preview_version,
    )
    if expected != preview.deployment_preview_id:
        raise ValueError("DeploymentPreview deterministic identity does not match content")
