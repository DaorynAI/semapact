"""Application service for provider-neutral deployment workflows."""

from __future__ import annotations

from semapact.deployment import (
    DeploymentAdapter,
    DeploymentPlan,
    DeploymentPreview,
    DeploymentSourceSnapshot,
    DeploymentTarget,
    build_deployment_plan_from_source,
)
from semapact.exceptions import ValidationError
from semapact.reconciliation import ReconciliationResult


class DeploymentService:
    """Application boundary over the generic deployment lifecycle."""

    def plan(
        self,
        source: DeploymentSourceSnapshot,
        target: DeploymentTarget,
    ) -> DeploymentPlan:
        return build_deployment_plan_from_source(source, target)

    def preview(
        self,
        plan: DeploymentPlan,
        *,
        adapter: DeploymentAdapter,
    ) -> DeploymentPreview:
        _validate_component_key(adapter.key, plan.target.platform, "deployment adapter")
        return adapter.preview(plan)

    def apply(
        self,
        plan: DeploymentPlan,
        preview: DeploymentPreview,
        *,
        adapter: DeploymentAdapter,
    ) -> None:
        """Apply one exact preview after the external execution boundary allows CD."""
        _validate_component_key(adapter.key, plan.target.platform, "deployment adapter")
        adapter.apply(plan, preview)

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
