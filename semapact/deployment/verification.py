"""Thin bridge from an exact DeploymentPlan to M1 runtime reconciliation."""

from __future__ import annotations

from open_data_contract_standard.model import OpenDataContractStandard, SchemaObject

from semapact.deployment.models import (
    DeploymentPlan,
    validate_deployment_plan_identity,
)
from semapact.exceptions import ValidationError
from semapact.observation.providers import RuntimeProvider
from semapact.reconciliation import ReconciliationResult, reconcile_governed_contract
from semapact.runtime import RuntimeAssetSpec


def verify_deployment_convergence(
    plan: DeploymentPlan,
    runtime_provider: RuntimeProvider,
) -> ReconciliationResult:
    """Observe and reconcile the exact desired state embedded in a DeploymentPlan.

    This function does not infer deployment causality or create a second convergence
    status model. Callers classify the returned result with the existing
    ``classify_reconciliation_status`` function.
    """
    validate_deployment_plan_identity(plan)

    provider_key = runtime_provider.key.strip().casefold()
    if provider_key != plan.target.platform:
        raise ValidationError(
            "Runtime provider does not match DeploymentPlan platform: "
            f"{provider_key!r} != {plan.target.platform!r}"
        )

    desired_contract = _contract_projection_from_plan(plan)
    assets = tuple(
        RuntimeAssetSpec(
            governed_asset=action.governed_asset,
            physical_name=action.physical_name,
        )
        for action in plan.actions
    )
    bindings = runtime_provider.resolve_bindings(
        runtime_target=plan.target.runtime_target,
        assets=assets,
    )
    observation = runtime_provider.observe(bindings=bindings)

    if observation.platform.strip().casefold() != plan.target.platform:
        raise ValidationError(
            "Observed runtime platform does not match DeploymentPlan platform"
        )

    return reconcile_governed_contract(
        desired_contract,
        observation,
        asset_bindings=bindings,
    )


def _contract_projection_from_plan(
    plan: DeploymentPlan,
) -> OpenDataContractStandard:
    schemas = [
        SchemaObject.model_validate_json(action.desired_state_json)
        for action in plan.actions
    ]
    # Reconciliation needs only exact contract identity/version plus governed schemas.
    # The schemas were validated when the DeploymentPlan was constructed, and the
    # deterministic plan identity was revalidated above.
    return OpenDataContractStandard.model_construct(
        id=plan.contract_id,
        version=plan.selected_version,
        schema_=schemas,
    )
