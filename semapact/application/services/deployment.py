"""Application service for provider-neutral deployment workflows."""

from __future__ import annotations

from semapact.contractops import AppliedContractRelease, ReleaseSnapshot
from semapact.deployment import (
    DeploymentAdapter,
    DeploymentAuthorization,
    DeploymentPlan,
    DeploymentPreview,
    DeploymentSourceSnapshot,
    DeploymentTarget,
    build_deployment_plan,
    build_deployment_plan_from_source,
)
from semapact.exceptions import ValidationError
from semapact.reconciliation import ReconciliationResult


class DeploymentService:
    """Application boundary over the generic deployment lifecycle."""

    def plan(
        self,
        release: ReleaseSnapshot | AppliedContractRelease | DeploymentSourceSnapshot,
        target: DeploymentTarget,
    ) -> DeploymentPlan:
        if isinstance(release, DeploymentSourceSnapshot):
            return build_deployment_plan_from_source(release, target)
        return build_deployment_plan(release, target)

    def preview(
        self,
        plan: DeploymentPlan,
        *,
        adapter: DeploymentAdapter,
    ) -> DeploymentPreview:
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
        _validate_component_key(adapter.key, plan.target.platform, "deployment adapter")
        adapter.execute(plan, preview, authorization)

    def verify(
        self,
        plan: DeploymentPlan,
        *,
        adapter: DeploymentAdapter,
    ) -> ReconciliationResult:
        _validate_component_key(adapter.key, plan.target.platform, "deployment adapter")
        return adapter.verify(plan)


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
