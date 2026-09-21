"""Boundary adapters for legacy deployment artifacts.

Legacy wire formats are verified with their historical deterministic identities and
then upgraded into canonical DeploymentPlan/DeploymentAuthorization objects. The
canonical domain models never persist legacy fields or versions.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from semapact.contractops.execution_models import AppliedContractRelease, ReleaseSnapshot
from semapact.contractops.integrity import (
    validate_applied_release_identity,
    validate_release_snapshot_identity,
)
from semapact.deployment.models import (
    SEMAPACT_DEPLOYMENT_AUTHORIZATION_NAMESPACE,
    SEMAPACT_DEPLOYMENT_PLAN_NAMESPACE,
    DeploymentAction,
    DeploymentAuthorization,
    DeploymentPlan,
    DeploymentTarget,
    compute_deployment_authorization_id,
    compute_deployment_plan_id,
)
from semapact.deployment.planner import build_deployment_actions
from semapact.utils.deterministic import deterministic_uuid5


def parse_deployment_plan_payload(payload: Mapping[str, Any]) -> DeploymentPlan:
    """Verify and upgrade a legacy plan payload into canonical v5."""
    value = dict(payload)
    version = _infer_plan_version(value)

    if version == "5" and not _has_legacy_plan_fields(value):
        return DeploymentPlan.model_validate(value)

    target = DeploymentTarget.model_validate(value.get("target"))
    actions = tuple(
        DeploymentAction.model_validate(action)
        for action in value.get("actions", ())
    )
    source_snapshot_id = _legacy_plan_source_id(value, version)
    revision_ref = _legacy_plan_revision_ref(value)
    contract_version = _legacy_plan_contract_version(value)
    contract_id = _required_text(value.get("contract_id"), "contract_id")

    expected_legacy_id = _compute_legacy_deployment_plan_id(
        version=version,
        source_snapshot_id=source_snapshot_id,
        contract_id=contract_id,
        revision_ref=revision_ref,
        contract_version=contract_version,
        release_id=_optional_text(value.get("release_id"))
        or (_optional_text(value.get("applied_release_id")) if version == "2" else None),
        release_plan_id=_optional_text(value.get("release_plan_id")),
        release=value.get("release"),
        target=target,
        actions=actions,
    )
    if value.get("deployment_plan_id") != expected_legacy_id:
        raise ValueError("Legacy DeploymentPlan deterministic identity does not match content")

    canonical_id = compute_deployment_plan_id(
        source_snapshot_id=source_snapshot_id,
        contract_id=contract_id,
        revision_ref=revision_ref,
        contract_version=contract_version,
        target=target,
        actions=actions,
    )
    return DeploymentPlan(
        deployment_plan_id=canonical_id,
        source_snapshot_id=source_snapshot_id,
        contract_id=contract_id,
        revision_ref=revision_ref,
        contract_version=contract_version,
        target=target,
        actions=actions,
    )


def serialize_deployment_plan_payload(plan: DeploymentPlan) -> dict[str, Any]:
    """Persist only the canonical DeploymentPlan wire shape."""
    return plan.model_dump(mode="json")


def parse_deployment_authorization_payload(
    payload: Mapping[str, Any],
) -> DeploymentAuthorization:
    """Verify and upgrade a legacy authorization payload into canonical v2."""
    value = dict(payload)
    if (
        "contract_ops_authorization_id" not in value
        and "applied_release_id" not in value
        and str(value.get("authorization_version", "2")) == "2"
    ):
        return DeploymentAuthorization.model_validate(value)

    deployment_plan_id = _required_text(
        value.get("deployment_plan_id"),
        "deployment_plan_id",
    )
    source_snapshot_id = _required_text(
        value.get("source_snapshot_id") or value.get("applied_release_id"),
        "source_snapshot_id",
    )
    authorization_reference = _required_text(
        value.get("authorization_reference")
        or value.get("contract_ops_authorization_id"),
        "authorization_reference",
    )
    authorization_kind = str(value.get("authorization_kind") or "contractops")
    allowed = value.get("allowed")
    if not isinstance(allowed, bool):
        raise ValueError("allowed must be boolean")

    expected_legacy_id = deterministic_uuid5(
        SEMAPACT_DEPLOYMENT_AUTHORIZATION_NAMESPACE,
        {
            "contract_ops_authorization_id": authorization_reference,
            "deployment_plan_id": deployment_plan_id,
            "applied_release_id": source_snapshot_id,
            "allowed": allowed,
        },
    )
    if value.get("deployment_authorization_id") != expected_legacy_id:
        raise ValueError(
            "Legacy DeploymentAuthorization deterministic identity does not match content"
        )

    canonical_id = compute_deployment_authorization_id(
        deployment_plan_id=deployment_plan_id,
        source_snapshot_id=source_snapshot_id,
        authorization_kind=authorization_kind,
        authorization_reference=authorization_reference,
        allowed=allowed,
    )
    return DeploymentAuthorization(
        deployment_authorization_id=canonical_id,
        deployment_plan_id=deployment_plan_id,
        source_snapshot_id=source_snapshot_id,
        allowed=allowed,
        authorization_kind=authorization_kind,
        authorization_reference=authorization_reference,
    )


def serialize_deployment_authorization_payload(
    authorization: DeploymentAuthorization,
) -> dict[str, Any]:
    """Persist only the canonical DeploymentAuthorization wire shape."""
    return authorization.model_dump(mode="json")


def build_legacy_deployment_plan(
    release: ReleaseSnapshot | AppliedContractRelease,
    target: DeploymentTarget,
) -> DeploymentPlan:
    """Adapt pre-ContractRelease release artifacts into one canonical plan.

    This is an explicit compatibility entrypoint. New workflows must plan from a
    DeploymentSourceSnapshot instead.
    """
    if isinstance(release, ReleaseSnapshot):
        validate_release_snapshot_identity(release)
        source_snapshot_id = release.release_snapshot_id
    elif isinstance(release, AppliedContractRelease):
        validate_applied_release_identity(release)
        source_snapshot_id = release.applied_release_id
    else:
        raise TypeError(
            "release must be ReleaseSnapshot or AppliedContractRelease, "
            f"got {type(release).__name__}"
        )
    if not isinstance(target, DeploymentTarget):
        raise TypeError(
            f"target must be DeploymentTarget, got {type(target).__name__}"
        )

    actions = build_deployment_actions(release.to_contract())
    plan_id = compute_deployment_plan_id(
        source_snapshot_id=source_snapshot_id,
        contract_id=release.contract_id,
        revision_ref=release.release_revision_ref,
        contract_version=release.selected_version,
        target=target,
        actions=actions,
    )
    return DeploymentPlan(
        deployment_plan_id=plan_id,
        source_snapshot_id=source_snapshot_id,
        contract_id=release.contract_id,
        revision_ref=release.release_revision_ref,
        contract_version=release.selected_version,
        target=target,
        actions=actions,
    )


def _infer_plan_version(value: Mapping[str, Any]) -> str:
    raw = value.get("plan_version")
    if raw is not None:
        version = str(raw)
    elif "applied_release_id" in value:
        version = "2"
    elif (
        "release_id" in value
        or "released_revision_ref" in value
        or "selected_version" in value
    ):
        version = "3"
    else:
        version = "5"
    if version not in {"2", "3", "4", "5"}:
        raise ValueError(f"Unsupported legacy DeploymentPlan version: {version}")
    return version


def _has_legacy_plan_fields(value: Mapping[str, Any]) -> bool:
    return any(
        field in value
        for field in (
            "applied_release_id",
            "release_id",
            "release_plan_id",
            "released_revision_ref",
            "selected_version",
            "release",
        )
    )


def _legacy_plan_source_id(value: Mapping[str, Any], version: str) -> str:
    if version == "2":
        raw = value.get("applied_release_id") or value.get("source_snapshot_id")
    elif version == "3":
        raw = value.get("release_id") or value.get("source_snapshot_id")
    else:
        raw = value.get("source_snapshot_id")
    return _required_text(raw, "source_snapshot_id")


def _legacy_plan_revision_ref(value: Mapping[str, Any]) -> str:
    return _required_text(
        value.get("revision_ref") or value.get("released_revision_ref"),
        "revision_ref",
    )


def _legacy_plan_contract_version(value: Mapping[str, Any]) -> str:
    return _required_text(
        value.get("contract_version") or value.get("selected_version"),
        "contract_version",
    )


def _compute_legacy_deployment_plan_id(
    *,
    version: str,
    source_snapshot_id: str,
    contract_id: str,
    revision_ref: str,
    contract_version: str,
    release_id: str | None,
    release_plan_id: str | None,
    release: object,
    target: DeploymentTarget,
    actions: tuple[DeploymentAction, ...],
) -> str:
    if version in {"2", "3"}:
        if release_id is None or release_plan_id is None:
            raise ValueError(
                f"Legacy DeploymentPlan v{version} requires release provenance"
            )
        release_key = "applied_release_id" if version == "2" else "release_id"
        return deterministic_uuid5(
            SEMAPACT_DEPLOYMENT_PLAN_NAMESPACE,
            {
                release_key: release_id,
                "contract_id": contract_id,
                "release_plan_id": release_plan_id,
                "released_revision_ref": revision_ref,
                "selected_version": contract_version,
                "target": target.model_dump(mode="json"),
                "actions": [action.model_dump(mode="json") for action in actions],
                "plan_version": version,
            },
        )

    has_release_id = release_id is not None
    has_release_plan = release_plan_id is not None
    if version == "4" and has_release_id != has_release_plan:
        raise ValueError(
            "Legacy DeploymentPlan release_id and release_plan_id must be provided together"
        )
    if version == "4" and release is not None and bool(release) != has_release_id:
        raise ValueError(
            "Legacy DeploymentPlan release flag conflicts with release provenance"
        )

    legacy_payload = {
        "source_snapshot_id": source_snapshot_id,
        "contract_id": contract_id,
        "revision_ref": revision_ref,
        "contract_version": contract_version,
        "release_id": release_id,
        "release_plan_id": release_plan_id if version == "4" else None,
        "target": target.model_dump(mode="json"),
        "actions": [action.model_dump(mode="json") for action in actions],
        "plan_version": version,
    }
    if version == "4":
        legacy_payload["release"] = has_release_id
    return deterministic_uuid5(SEMAPACT_DEPLOYMENT_PLAN_NAMESPACE, legacy_payload)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None
