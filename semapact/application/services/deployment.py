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
from semapact.exceptions import ValidationError
from semapact.observation import RuntimeProvider
from semapact.reconciliation import ReconciliationResult


class DeploymentService:
    """Application boundary over the generic deployment lifecycle."""

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
        adapter: DeploymentAdapter,
    ) -> DeploymentPreview:
        """Delegate the complete read-only deployment workflow to the adapter."""
        _validate_component_key(adapter.key, plan.target.platform, "deployment adapter")
        return adapter.preview(plan)

    def execute(
        self,
        plan: DeploymentPlan,
        preview: DeploymentPreview,
        authorization: DeploymentAuthorization,
        *,
        adapter: DeploymentAdapter,
    ) -> None:
        """Delegate the complete exact side-effect workflow to the adapter."""
        _validate_component_key(adapter.key, plan.target.platform, "deployment adapter")
        adapter.execute(plan, preview, authorization)

    def verify(
        self,
        plan: DeploymentPlan,
        *,
        runtime_provider: RuntimeProvider,
    ) -> ReconciliationResult:
        """Verify exact plan convergence through the existing reconciliation path."""
        return verify_deployment_convergence(plan, runtime_provider)


def _validate_component_key(
    actual: str,
    expected: str,
    component: str,
) -> None:
    if actual.strip().casefold() != expected.strip().casefold():
        raise ValidationError(
            f"{component.capitalize()} does not match DeploymentPlan platform: "
            f"{actual!r} != {expected!r}"
        )
