"""Explicit compatibility adapters for legacy deployment artifacts.

Canonical deployment models validate canonical field names only. Legacy JSON is
upgraded or serialized here at the boundary so domain models do not hide migration
behavior in Pydantic validators/serializers.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from semapact.deployment.models import DeploymentAuthorization, DeploymentPlan


def parse_deployment_plan_payload(payload: Mapping[str, Any]) -> DeploymentPlan:
    """Adapt a legacy or canonical plan payload into DeploymentPlan."""
    value = dict(payload)
    raw_version = value.get("plan_version")
    if raw_version is None:
        if "applied_release_id" in value:
            version = "2"
        elif (
            "release_id" in value
            or "released_revision_ref" in value
            or "selected_version" in value
        ):
            version = "3"
        else:
            return DeploymentPlan.model_validate(value)
        value["plan_version"] = version
    else:
        version = str(raw_version)

    if version == "4":
        legacy_release = value.pop("release", None)
        has_release_provenance = bool(
            value.get("release_id") or value.get("release_plan_id")
        )
        if legacy_release is not None and bool(legacy_release) != has_release_provenance:
            raise ValueError(
                "Legacy DeploymentPlan release flag conflicts with release provenance"
            )
        return DeploymentPlan.model_validate(value)

    if version in {"2", "3"}:
        legacy_release_id = value.get("release_id") or value.get(
            "applied_release_id"
        )
        value.setdefault("source_snapshot_id", legacy_release_id)
        value.setdefault("revision_ref", value.get("released_revision_ref"))
        value.setdefault("contract_version", value.get("selected_version"))
        value.setdefault("release_id", legacy_release_id)
        value.pop("applied_release_id", None)
        value.pop("released_revision_ref", None)
        value.pop("selected_version", None)

    return DeploymentPlan.model_validate(value)


def serialize_deployment_plan_payload(plan: DeploymentPlan) -> dict[str, Any]:
    """Serialize DeploymentPlan using its historical wire format when required."""
    payload = plan.model_dump(mode="json")
    if plan.plan_version == "4":
        payload["release"] = plan.is_release
        return payload
    if plan.plan_version not in {"2", "3"}:
        return payload

    payload["released_revision_ref"] = payload.pop("revision_ref")
    payload["selected_version"] = payload.pop("contract_version")
    payload.pop("source_snapshot_id", None)
    if plan.plan_version == "2":
        payload["applied_release_id"] = payload.pop("release_id")
    return payload


def parse_deployment_authorization_payload(
    payload: Mapping[str, Any],
) -> DeploymentAuthorization:
    """Adapt a legacy or canonical authorization payload."""
    value = dict(payload)
    if "source_snapshot_id" not in value:
        contractops_id = value.get("contract_ops_authorization_id")
        release_id = value.get("applied_release_id")
        if contractops_id is not None and release_id is not None:
            value["source_snapshot_id"] = release_id
            value["authorization_kind"] = "contractops"
            value["authorization_reference"] = contractops_id
            value["authorization_version"] = "1"
            value.pop("contract_ops_authorization_id", None)
            value.pop("applied_release_id", None)
    return DeploymentAuthorization.model_validate(value)


def serialize_deployment_authorization_payload(
    authorization: DeploymentAuthorization,
) -> dict[str, Any]:
    """Serialize authorization using the v1 wire shape only when requested."""
    payload = authorization.model_dump(mode="json")
    if authorization.authorization_version != "1":
        return payload
    payload["contract_ops_authorization_id"] = payload.pop(
        "authorization_reference"
    )
    payload["applied_release_id"] = payload.pop("source_snapshot_id")
    payload.pop("authorization_kind", None)
    payload.pop("authorization_version", None)
    return payload
