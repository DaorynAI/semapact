"""Application service for provider-neutral deployment workflows."""

from __future__ import annotations

from semapact.contractops import AppliedContractRelease
from semapact.deployment import (
    DeploymentAdapter,
    DeploymentAuthorization,
    DeploymentPlan,
    DeploymentPreview,
    DeploymentTarget,
    build_deployment_plan,
    verify_deployment_convergence,
)
from semapact.deployment.models import validate_deployment_plan_identity
from semapact.exceptions import ValidationError
from semapact.observation import RuntimeProvider
from semapact.reconciliation import ReconciliationResult
from semapact.runtime import RuntimeAssetSpec


class DeploymentService:
    """Compose existing deployment domain/provider boundaries for interfaces.

    The service owns orchestration only. It does not re-run governance, approval,
    versioning, deployment translation, or reconciliation rules.
    """

    def plan(
        self,
        release: AppliedContractRelease,
        target: DeploymentTarget,
    ) -> DeploymentPlan:
        return build_deployment_plan(release, target)

    def preview(
        self,
        plan: DeploymentPlan,
        *,
        runtime_provider: RuntimeProvider,
        adapter: DeploymentAdapter,
    ) -> DeploymentPreview:
        """Observe the exact plan scope and delegate native translation to adapter."""
        validate_deployment_plan_identity(plan)
        _validate_component_key(runtime_provider.key, plan.target.platform, "runtime provider")
        _validate_component_key(adapter.key, plan.target.platform, "deployment adapter")

        assets = _runtime_assets_from_plan(plan)
        bindings = runtime_provider.resolve_bindings(
            runtime_target=plan.target.runtime_target,
            assets=assets,
        )
        observation = runtime_provider.observe(bindings=bindings)
        _validate_source_reference(observation.source_identifier, plan.target.source_reference)
        return adapter.preview(plan, observation)

    def execute(
        self,
        plan: DeploymentPlan,
        preview: DeploymentPreview,
        authorization: DeploymentAuthorization,
        *,
        adapter: DeploymentAdapter,
    ) -> None:
        """Delegate the exact authorized side effect to the provider adapter."""
        _validate_component_key(adapter.key, plan.target.platform, "deployment adapter")
        adapter.execute(plan, preview, authorization)

    def verify(
        self,
        plan: DeploymentPlan,
        *,
        runtime_provider: RuntimeProvider,
    ) -> ReconciliationResult:
        """Verify exact plan convergence through the existing M1 bridge."""
        return verify_deployment_convergence(plan, runtime_provider)


def _runtime_assets_from_plan(plan: DeploymentPlan) -> tuple[RuntimeAssetSpec, ...]:
    return tuple(
        RuntimeAssetSpec(
            governed_asset=action.governed_asset,
            physical_name=action.physical_name,
        )
        for action in plan.actions
    )


def _validate_component_key(actual: str, expected: str, component: str) -> None:
    if actual.strip().casefold() != expected.strip().casefold():
        raise ValidationError(
            f"{component.capitalize()} does not match DeploymentPlan platform: "
            f"{actual!r} != {expected!r}"
        )


def _validate_source_reference(actual: str, expected: str) -> None:
    if actual.strip() != expected.strip():
        raise ValidationError(
            "Runtime observation source does not match DeploymentPlan source reference: "
            f"{actual!r} != {expected!r}"
        )
