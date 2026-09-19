"""Application service for provider-neutral deployment workflows."""

from __future__ import annotations

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.contractops import AppliedContractRelease
from semapact.deployment import (
    DeploymentAdapter,
    DeploymentAssessment,
    DeploymentAuthorization,
    DeploymentPlan,
    DeploymentPreview,
    DeploymentTarget,
    build_deployment_plan,
)
from semapact.exceptions import ValidationError
from semapact.reconciliation import ReconciliationResult


class DeploymentService:
    """Application boundary over the generic deployment lifecycle."""

    def assess(
        self,
        contract: OpenDataContractStandard,
        *,
        candidate_revision_ref: str,
        target: DeploymentTarget,
        adapter: DeploymentAdapter,
    ) -> DeploymentAssessment:
        _validate_component_key(adapter.key, target.platform, "deployment adapter")
        return adapter.assess(
            contract,
            candidate_revision_ref=candidate_revision_ref,
            target=target,
        )

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
