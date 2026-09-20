"""Provider-neutral immutable deployment planning, preview, and authorization artifacts."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Literal, Sequence

from open_data_contract_standard.model import SchemaObject
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
    model_validator,
)

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
    """Exact runtime target for one DeploymentPlan, excluding credentials."""

    platform: str
    runtime_target: str
    source_reference: str
    server_name: str | None = None

    @field_validator("platform")
    @classmethod
    def _normalize_platform(cls, value: str) -> str:
        cleaned = value.strip().casefold()
        if not cleaned:
            raise ValueError("platform must not be empty")
        return cleaned

    @field_validator("runtime_target", "source_reference")
    @classmethod
    def _normalize_required_target_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("runtime target fields must not be empty")
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
    """Pure deterministic runtime convergence plan for one exact source snapshot."""

    deployment_plan_id: str
    source_snapshot_id: str
    contract_id: str
    revision_ref: str
    contract_version: str
    target: DeploymentTarget
    actions: tuple[DeploymentAction, ...]
    release: bool = Field(strict=True)
    release_id: str | None = None
    release_plan_id: str | None = None
    plan_version: Literal["2", "3", "4"] = "4"

    @model_validator(mode="before")
    @classmethod
    def _upgrade_legacy_plan_payload(cls, value):
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        raw_version = payload.get("plan_version")
        if raw_version is None:
            if "applied_release_id" in payload:
                version = "2"
            elif (
                "release_id" in payload
                or "released_revision_ref" in payload
                or "selected_version" in payload
            ):
                version = "3"
            else:
                return payload
            payload["plan_version"] = version
        else:
            version = str(raw_version)
        if version not in {"2", "3"}:
            return payload

        legacy_release_id = payload.get("release_id") or payload.get(
            "applied_release_id"
        )
        payload.setdefault("source_snapshot_id", legacy_release_id)
        payload.setdefault("revision_ref", payload.get("released_revision_ref"))
        payload.setdefault("contract_version", payload.get("selected_version"))
        payload.setdefault("release", True)
        payload.setdefault("release_id", legacy_release_id)
        payload.pop("applied_release_id", None)
        payload.pop("released_revision_ref", None)
        payload.pop("selected_version", None)
        return payload

    @field_validator(
        "deployment_plan_id",
        "source_snapshot_id",
        "contract_id",
        "revision_ref",
        "contract_version",
    )
    @classmethod
    def _require_plan_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned

    @field_validator("release_id", "release_plan_id")
    @classmethod
    def _normalize_optional_plan_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def _validate_action_order_and_identity(self) -> "DeploymentPlan":
        governed_assets = [action.governed_asset for action in self.actions]
        if governed_assets != sorted(governed_assets):
            raise ValueError("DeploymentPlan actions must be ordered by governed_asset")
        if len(governed_assets) != len(set(governed_assets)):
            raise ValueError("DeploymentPlan cannot contain duplicate governed assets")

        if self.release:
            if self.release_id is None or self.release_plan_id is None:
                raise ValueError(
                    "Release DeploymentPlan requires release_id and release_plan_id"
                )
        elif self.release_id is not None or self.release_plan_id is not None:
            raise ValueError(
                "Non-release DeploymentPlan must not contain release provenance"
            )

        validate_deployment_plan_identity(self)
        return self

    @model_serializer(mode="wrap")
    def _serialize_legacy_plan(self, handler):
        payload = handler(self)
        if self.plan_version not in {"2", "3"}:
            return payload

        payload["released_revision_ref"] = payload.pop("revision_ref")
        payload["selected_version"] = payload.pop("contract_version")
        payload.pop("source_snapshot_id", None)
        payload.pop("release", None)
        if self.plan_version == "2":
            payload["applied_release_id"] = payload.pop("release_id")
        return payload

    @property
    def applied_release_id(self) -> str:
        """Compatibility alias for callers using the v2 release field."""
        if self.release_id is None:
            raise ValueError("Non-release DeploymentPlan has no applied release")
        return self.release_id

    @property
    def released_revision_ref(self) -> str:
        """Compatibility alias for pre-v4 callers."""
        return self.revision_ref

    @property
    def selected_version(self) -> str:
        """Compatibility alias for pre-v4 callers."""
        return self.contract_version


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
    """Authorization bound to one exact DeploymentPlan source snapshot."""

    deployment_authorization_id: str
    deployment_plan_id: str
    source_snapshot_id: str
    allowed: bool = Field(strict=True)
    authorization_kind: Literal["contractops", "governance"] = "contractops"
    authorization_reference: str
    authorization_version: Literal["1", "2"] = "2"

    @model_validator(mode="before")
    @classmethod
    def _upgrade_legacy_authorization_payload(cls, value):
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        if "source_snapshot_id" in payload:
            return payload
        contractops_id = payload.get("contract_ops_authorization_id")
        release_id = payload.get("applied_release_id")
        if contractops_id is None or release_id is None:
            return payload
        payload["source_snapshot_id"] = release_id
        payload["authorization_kind"] = "contractops"
        payload["authorization_reference"] = contractops_id
        payload["authorization_version"] = "1"
        payload.pop("contract_ops_authorization_id", None)
        payload.pop("applied_release_id", None)
        return payload

    @field_validator(
        "deployment_authorization_id",
        "deployment_plan_id",
        "source_snapshot_id",
        "authorization_reference",
    )
    @classmethod
    def _require_authorization_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned

    @model_validator(mode="after")
    def _validate_identity(self) -> "DeploymentAuthorization":
        validate_deployment_authorization_identity(self)
        return self

    @model_serializer(mode="wrap")
    def _serialize_legacy_authorization(self, handler):
        payload = handler(self)
        if self.authorization_version != "1":
            return payload
        payload["contract_ops_authorization_id"] = payload.pop(
            "authorization_reference"
        )
        payload["applied_release_id"] = payload.pop("source_snapshot_id")
        payload.pop("authorization_kind", None)
        payload.pop("authorization_version", None)
        return payload

    @property
    def contract_ops_authorization_id(self) -> str:
        """Compatibility accessor for ContractOps-backed authorization."""
        if self.authorization_kind != "contractops":
            raise ValueError("Authorization is not backed by ContractOps")
        return self.authorization_reference

    @property
    def applied_release_id(self) -> str:
        """Compatibility accessor for pre-v2 deployment authorization."""
        return self.source_snapshot_id


def compute_deployment_plan_id(
    *,
    source_snapshot_id: str | None = None,
    release_id: str | None = None,
    applied_release_id: str | None = None,
    contract_id: str,
    revision_ref: str | None = None,
    released_revision_ref: str | None = None,
    contract_version: str | None = None,
    selected_version: str | None = None,
    release_plan_id: str | None = None,
    release: bool = True,
    target: DeploymentTarget,
    actions: Sequence[DeploymentAction],
    plan_version: str | None = None,
) -> str:
    if plan_version is None:
        if applied_release_id is not None:
            plan_version = "2"
        elif source_snapshot_id is not None and release is False:
            plan_version = "4"
        else:
            plan_version = "3"

    legacy_release_id = _resolve_optional_legacy_release_id(
        release_id=release_id,
        applied_release_id=applied_release_id,
    )
    resolved_source_id = (
        source_snapshot_id.strip()
        if isinstance(source_snapshot_id, str) and source_snapshot_id.strip()
        else legacy_release_id
    )
    if resolved_source_id is None:
        raise ValueError("source_snapshot_id is required")

    resolved_revision = _resolve_text_pair(
        revision_ref,
        released_revision_ref,
        "revision_ref",
    )
    resolved_version = _resolve_text_pair(
        contract_version,
        selected_version,
        "contract_version",
    )

    if plan_version in {"2", "3"}:
        if legacy_release_id is None:
            legacy_release_id = resolved_source_id
        if release_plan_id is None:
            raise ValueError("legacy DeploymentPlan requires release_plan_id")
        release_key = "applied_release_id" if plan_version == "2" else "release_id"
        return deterministic_uuid5(
            SEMAPACT_DEPLOYMENT_PLAN_NAMESPACE,
            {
                release_key: legacy_release_id,
                "contract_id": contract_id,
                "release_plan_id": release_plan_id,
                "released_revision_ref": resolved_revision,
                "selected_version": resolved_version,
                "target": target.model_dump(mode="json"),
                "actions": [action.model_dump(mode="json") for action in actions],
                "plan_version": plan_version,
            },
        )

    if plan_version != "4":
        raise ValueError(f"Unsupported DeploymentPlan version: {plan_version}")
    if release and (release_id is None or release_plan_id is None):
        raise ValueError("Release DeploymentPlan requires release provenance")
    if not release and (release_id is not None or release_plan_id is not None):
        raise ValueError("Non-release DeploymentPlan cannot contain release provenance")

    return deterministic_uuid5(
        SEMAPACT_DEPLOYMENT_PLAN_NAMESPACE,
        {
            "source_snapshot_id": resolved_source_id,
            "contract_id": contract_id,
            "revision_ref": resolved_revision,
            "contract_version": resolved_version,
            "release": release,
            "release_id": release_id,
            "release_plan_id": release_plan_id,
            "target": target.model_dump(mode="json"),
            "actions": [action.model_dump(mode="json") for action in actions],
            "plan_version": plan_version,
        },
    )


def compute_deployment_authorization_id(
    *,
    deployment_plan_id: str,
    source_snapshot_id: str | None = None,
    authorization_kind: str = "contractops",
    authorization_reference: str | None = None,
    allowed: bool,
    contract_ops_authorization_id: str | None = None,
    applied_release_id: str | None = None,
    authorization_version: str | None = None,
) -> str:
    if authorization_version is None:
        authorization_version = (
            "1"
            if contract_ops_authorization_id is not None
            or applied_release_id is not None
            else "2"
        )

    if authorization_version == "1":
        contractops_id = _resolve_text_pair(
            authorization_reference,
            contract_ops_authorization_id,
            "contract_ops_authorization_id",
        )
        release_id = _resolve_text_pair(
            source_snapshot_id,
            applied_release_id,
            "applied_release_id",
        )
        return deterministic_uuid5(
            SEMAPACT_DEPLOYMENT_AUTHORIZATION_NAMESPACE,
            {
                "contract_ops_authorization_id": contractops_id,
                "deployment_plan_id": deployment_plan_id,
                "applied_release_id": release_id,
                "allowed": allowed,
            },
        )

    if authorization_version != "2":
        raise ValueError(
            f"Unsupported DeploymentAuthorization version: {authorization_version}"
        )
    if authorization_kind not in {"contractops", "governance"}:
        raise ValueError("Unsupported deployment authorization kind")
    source_id = _resolve_text_pair(
        source_snapshot_id,
        None,
        "source_snapshot_id",
    )
    reference = _resolve_text_pair(
        authorization_reference,
        None,
        "authorization_reference",
    )
    return deterministic_uuid5(
        SEMAPACT_DEPLOYMENT_AUTHORIZATION_NAMESPACE,
        {
            "authorization_kind": authorization_kind,
            "authorization_reference": reference,
            "deployment_plan_id": deployment_plan_id,
            "source_snapshot_id": source_id,
            "allowed": allowed,
            "authorization_version": authorization_version,
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


def _resolve_optional_legacy_release_id(
    *,
    release_id: str | None,
    applied_release_id: str | None,
) -> str | None:
    values = {
        value.strip()
        for value in (release_id, applied_release_id)
        if isinstance(value, str) and value.strip()
    }
    if len(values) > 1:
        raise ValueError(
            "release_id and applied_release_id must identify the same release"
        )
    return values.pop() if values else None


def _resolve_text_pair(
    primary: str | None,
    compatibility: str | None,
    field_name: str,
) -> str:
    values = {
        value.strip()
        for value in (primary, compatibility)
        if isinstance(value, str) and value.strip()
    }
    if not values:
        raise ValueError(f"{field_name} is required")
    if len(values) != 1:
        raise ValueError(f"{field_name} compatibility values do not match")
    return values.pop()


def validate_deployment_plan_identity(plan: DeploymentPlan) -> None:
    expected = compute_deployment_plan_id(
        source_snapshot_id=plan.source_snapshot_id,
        release_id=plan.release_id,
        contract_id=plan.contract_id,
        release_plan_id=plan.release_plan_id,
        revision_ref=plan.revision_ref,
        contract_version=plan.contract_version,
        release=plan.release,
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
        deployment_plan_id=authorization.deployment_plan_id,
        source_snapshot_id=authorization.source_snapshot_id,
        authorization_kind=authorization.authorization_kind,
        authorization_reference=authorization.authorization_reference,
        allowed=authorization.allowed,
        authorization_version=authorization.authorization_version,
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
