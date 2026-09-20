"""Canonical contract-first deployment workflow orchestration."""

from __future__ import annotations

from datetime import date

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.application.models.deployment_workflow import (
    DeploymentBundle,
    build_deployment_bundle,
)
from semapact.application.services.deployment import DeploymentService
from semapact.application.services.release_planning import ReleasePlanningService
from semapact.contractops import build_release_snapshot
from semapact.deployment import DeploymentAdapter, DeploymentTarget


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
    ) -> DeploymentBundle:
        """Build the immutable CI handoff bundle without side-effect authorization."""
        release = self._release_planning.plan(
            base_contract,
            candidate_contract,
            effective_date=effective_date,
            base_revision_ref=base_revision_ref,
            candidate_revision_ref=candidate_revision_ref,
            authority_reference=authority_reference,
        )
        snapshot = build_release_snapshot(
            candidate_contract,
            candidate_revision_ref=candidate_revision_ref,
            decision=release.decision,
            change_set=release.change_set,
            release_plan=release.release_plan,
            version_resolution=release.version_resolution,
        )
        plan = self._deployment.plan(snapshot, target)
        preview = self._deployment.preview(plan, adapter=adapter)
        return build_deployment_bundle(
            decision=release.decision,
            change_set=release.change_set,
            release_plan=release.release_plan,
            version_resolution=release.version_resolution,
            release_snapshot=snapshot,
            deployment_plan=plan,
            review_preview=preview,
        )
