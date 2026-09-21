"""Pure compilation of canonical deployment sources into convergence plans."""

from __future__ import annotations

from open_data_contract_standard.model import OpenDataContractStandard, SchemaObject

from semapact.deployment.models import (
    DeploymentAction,
    DeploymentActionKind,
    DeploymentPlan,
    DeploymentTarget,
    compute_deployment_plan_id,
)
from semapact.deployment.source import DeploymentSourceSnapshot
from semapact.lifecycle.identity import normalize_identity_name
from semapact.runtime import runtime_asset_specs_from_contract
from semapact.utils.deterministic import canonical_compact_json


def build_deployment_plan_from_source(
    source: DeploymentSourceSnapshot,
    target: DeploymentTarget,
) -> DeploymentPlan:
    """Build a v5 plan from one exact deployment source snapshot."""
    if not isinstance(source, DeploymentSourceSnapshot):
        raise TypeError(
            "source must be DeploymentSourceSnapshot, "
            f"got {type(source).__name__}"
        )
    if not isinstance(target, DeploymentTarget):
        raise TypeError(
            f"target must be DeploymentTarget, got {type(target).__name__}"
        )

    contract = source.to_contract()
    ordered_actions = build_deployment_actions(contract)
    deployment_plan_id = compute_deployment_plan_id(
        source_snapshot_id=source.source_snapshot_id,
        contract_id=source.contract_id,
        revision_ref=source.revision_ref,
        contract_version=source.contract_version,
        target=target,
        actions=ordered_actions,
        plan_version="1",
    )
    return DeploymentPlan(
        deployment_plan_id=deployment_plan_id,
        source_snapshot_id=source.source_snapshot_id,
        contract_id=source.contract_id,
        revision_ref=source.revision_ref,
        contract_version=source.contract_version,
        target=target,
        actions=ordered_actions,
        plan_version="1",
    )

def build_deployment_actions(
    contract: OpenDataContractStandard,
) -> tuple[DeploymentAction, ...]:
    """Project candidate/released ODCS state into provider-neutral desired actions.

    Actions are desired-state facts only. They are not executable authority until
    they are bound into an exact DeploymentPlan derived from a release snapshot.
    """
    if not isinstance(contract, OpenDataContractStandard):
        raise TypeError(
            "contract must be OpenDataContractStandard, "
            f"got {type(contract).__name__}"
        )

    asset_specs = runtime_asset_specs_from_contract(contract)
    specs_by_asset = {spec.governed_asset: spec for spec in asset_specs}

    actions: list[DeploymentAction] = []
    for schema in contract.schema_ or []:
        raw_name = getattr(schema, "name", None)
        if raw_name is None:
            raise RuntimeError("Governed schema identity unexpectedly missing")
        governed_asset = normalize_identity_name(str(raw_name), "Schema")
        spec = specs_by_asset[governed_asset]
        actions.append(
            DeploymentAction(
                kind=DeploymentActionKind.ENSURE_ASSET_STATE,
                governed_asset=governed_asset,
                physical_name=spec.physical_name,
                desired_state_json=_canonical_schema_json(schema),
            )
        )

    return tuple(sorted(actions, key=lambda action: action.governed_asset))


def _canonical_schema_json(schema: SchemaObject) -> str:
    payload = schema.model_dump(mode="json", by_alias=True, exclude_none=True)
    return canonical_compact_json(payload)
