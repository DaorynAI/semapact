"""Pure compilation of applied contract releases into deployment convergence plans."""

from __future__ import annotations

from open_data_contract_standard.model import SchemaObject

from semapact.contractops.execution_models import AppliedContractRelease
from semapact.contractops.integrity import validate_applied_release_identity
from semapact.deployment.models import (
    DeploymentAction,
    DeploymentActionKind,
    DeploymentPlan,
    DeploymentTarget,
    compute_deployment_plan_id,
)
from semapact.lifecycle.identity import normalize_identity_name
from semapact.runtime import runtime_asset_specs_from_contract
from semapact.utils.deterministic import canonical_compact_json


def build_deployment_plan(
    release: AppliedContractRelease,
    target: DeploymentTarget,
) -> DeploymentPlan:
    """Build one deterministic provider-neutral convergence plan.

    Planning consumes exact released desired state only. It does not observe runtime,
    choose CREATE/ALTER/DROP operations, contact a provider, or recompute governance.
    """
    if not isinstance(release, AppliedContractRelease):
        raise TypeError(
            f"release must be AppliedContractRelease, got {type(release).__name__}"
        )
    if not isinstance(target, DeploymentTarget):
        raise TypeError(
            f"target must be DeploymentTarget, got {type(target).__name__}"
        )

    validate_applied_release_identity(release)
    contract = release.to_contract()
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

    ordered_actions = tuple(sorted(actions, key=lambda action: action.governed_asset))
    deployment_plan_id = compute_deployment_plan_id(
        applied_release_id=release.applied_release_id,
        contract_id=release.contract_id,
        release_plan_id=release.release_plan_id,
        released_revision_ref=release.release_revision_ref,
        selected_version=release.selected_version,
        target=target,
        actions=ordered_actions,
    )

    return DeploymentPlan(
        deployment_plan_id=deployment_plan_id,
        applied_release_id=release.applied_release_id,
        contract_id=release.contract_id,
        release_plan_id=release.release_plan_id,
        released_revision_ref=release.release_revision_ref,
        selected_version=release.selected_version,
        target=target,
        actions=ordered_actions,
    )


def _canonical_schema_json(schema: SchemaObject) -> str:
    payload = schema.model_dump(mode="json", by_alias=True, exclude_none=True)
    return canonical_compact_json(payload)
