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
from semapact.deployment.models import validate_deployment_authorization_identity
from semapact.exceptions import ContractOpsAuthorizationError, ValidationError
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

    def execute(
        self,
        plan: DeploymentPlan,
        preview: DeploymentPreview,
        authorization: DeploymentAuthorization,
        *,
        adapter: DeploymentAdapter,
    ) -> None:
        """Compatibility wrapper for legacy in-process authorization callers."""
        _validate_component_key(adapter.key, plan.target.platform, "deployment adapter")
        validate_deployment_authorization_identity(authorization)
        if not authorization.allowed:
            raise ContractOpsAuthorizationError(
                "DeploymentAuthorization is not allowed"
            )
        if authorization.deployment_plan_id != plan.deployment_plan_id:
            raise ContractOpsAuthorizationError(
                "DeploymentAuthorization is not bound to this DeploymentPlan"
            )
        if authorization.source_snapshot_id != plan.source_snapshot_id:
            raise ContractOpsAuthorizationError(
                "DeploymentAuthorization source does not match DeploymentPlan"
            )
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
