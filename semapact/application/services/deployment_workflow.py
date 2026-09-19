"""Canonical contract-first deployment workflow orchestration."""

from __future__ import annotations

from datetime import date

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.application.models.deployment_workflow import (
    DeploymentWorkflowAssessment,
)
from semapact.application.services.deployment import DeploymentService
from semapact.application.services.release_planning import ReleasePlanningService
from semapact.deployment import DeploymentAdapter, DeploymentTarget
from semapact.exceptions import ValidationError


class DeploymentWorkflowService:
    """Compose release planning and runtime assessment without inventing authority."""

    def __init__(
        self,
        *,
        release_planning_service: ReleasePlanningService | None = None,
        deployment_service: DeploymentService | None = None,
    ) -> None:
        self._release_planning = release_planning_service or ReleasePlanningService()
        self._deployment = deployment_service or DeploymentService()

    def assess(
        self,
        base_contract: OpenDataContractStandard,
        candidate_contract: OpenDataContractStandard,
        *,
        effective_date: date | str,
        base_revision_ref: str,
        candidate_revision_ref: str,
        target: DeploymentTarget,
        adapter: DeploymentAdapter,
        authority_reference: str | None = None,
    ) -> DeploymentWorkflowAssessment:
        """Plan governed change and assess runtime without APPLY/DEPLOY authority."""
        release = self._release_planning.plan(
            base_contract,
            candidate_contract,
            effective_date=effective_date,
            base_revision_ref=base_revision_ref,
            candidate_revision_ref=candidate_revision_ref,
            authority_reference=authority_reference,
        )
        deployment = self._deployment.assess(
            candidate_contract,
            candidate_revision_ref=candidate_revision_ref,
            target=target,
            adapter=adapter,
        )

        if deployment.contract_id != release.release_plan.contract_id:
            raise ValidationError(
                "Deployment assessment contract does not match release planning context"
            )
        if deployment.candidate_revision_ref != release.release_plan.release_revision_ref:
            raise ValidationError(
                "Deployment assessment revision does not match release planning context"
            )

        return DeploymentWorkflowAssessment(
            release=release,
            deployment=deployment,
        )
