"""Application artifacts for contract-first deployment workflows."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from semapact.contractops import (
    ChangeSet,
    ReleasePlan,
    ReleaseSnapshot,
    VersionResolution,
)
from semapact.deployment import DeploymentPlan, DeploymentPreview
from semapact.governance import GovernanceDecision
from semapact.reconciliation import ReconciliationResult, RuntimeDriftStatus
from semapact.utils.deterministic import canonical_compact_json


class DeploymentExecutionResult(BaseModel):
    """Application result for one bundle-driven CD execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle_digest: str
    deployment_plan_id: str
    authorization_id: str
    fresh_preview: DeploymentPreview
    reconciliation: ReconciliationResult
    status: RuntimeDriftStatus
    review_preview_changed: bool


class DeploymentBundle(BaseModel):
    """Immutable CI-to-CD package around existing canonical domain artifacts.

    The bundle is transport and integrity boundary only. It does not add deployment
    authority; approval and authorization remain separate facts.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle_digest: str
    decision: GovernanceDecision
    change_set: ChangeSet
    release_plan: ReleasePlan
    version_resolution: VersionResolution
    release_snapshot: ReleaseSnapshot
    deployment_plan: DeploymentPlan
    review_preview: DeploymentPreview
    bundle_version: Literal["1"] = "1"

    @model_validator(mode="after")
    def _validate_bundle_links(self) -> "DeploymentBundle":
        if self.change_set.contract_id != self.decision.contract_id:
            raise ValueError("DeploymentBundle decision/change-set contract mismatch")
        if self.release_plan.change_set_id != self.change_set.change_set_id:
            raise ValueError("DeploymentBundle release plan does not match ChangeSet")
        if self.release_plan.decision_id != self.decision.decision_id:
            raise ValueError("DeploymentBundle release plan does not match decision")
        if self.version_resolution.release_plan_id != self.release_plan.release_plan_id:
            raise ValueError(
                "DeploymentBundle version resolution does not match ReleasePlan"
            )

        snapshot = self.release_snapshot
        if snapshot.decision_id != self.decision.decision_id:
            raise ValueError("DeploymentBundle snapshot does not match decision")
        if snapshot.change_set_id != self.change_set.change_set_id:
            raise ValueError("DeploymentBundle snapshot does not match ChangeSet")
        if snapshot.release_plan_id != self.release_plan.release_plan_id:
            raise ValueError("DeploymentBundle snapshot does not match ReleasePlan")
        if (
            snapshot.version_resolution_id
            != self.version_resolution.version_resolution_id
        ):
            raise ValueError(
                "DeploymentBundle snapshot does not match VersionResolution"
            )

        plan = self.deployment_plan
        if plan.release_id != snapshot.release_snapshot_id:
            raise ValueError("DeploymentBundle plan does not match ReleaseSnapshot")
        if plan.contract_id != snapshot.contract_id:
            raise ValueError("DeploymentBundle plan/snapshot contract mismatch")
        if plan.release_plan_id != snapshot.release_plan_id:
            raise ValueError("DeploymentBundle plan/snapshot release-plan mismatch")
        if plan.released_revision_ref != snapshot.release_revision_ref:
            raise ValueError("DeploymentBundle plan/snapshot revision mismatch")
        if plan.selected_version != snapshot.selected_version:
            raise ValueError("DeploymentBundle plan/snapshot version mismatch")

        if self.review_preview.deployment_plan_id != plan.deployment_plan_id:
            raise ValueError("DeploymentBundle preview does not match DeploymentPlan")

        expected = compute_deployment_bundle_digest(
            decision=self.decision,
            change_set=self.change_set,
            release_plan=self.release_plan,
            version_resolution=self.version_resolution,
            release_snapshot=self.release_snapshot,
            deployment_plan=self.deployment_plan,
            review_preview=self.review_preview,
            bundle_version=self.bundle_version,
        )
        if self.bundle_digest != expected:
            raise ValueError("DeploymentBundle digest does not match content")
        return self


def build_deployment_bundle(
    *,
    decision: GovernanceDecision,
    change_set: ChangeSet,
    release_plan: ReleasePlan,
    version_resolution: VersionResolution,
    release_snapshot: ReleaseSnapshot,
    deployment_plan: DeploymentPlan,
    review_preview: DeploymentPreview,
) -> DeploymentBundle:
    """Package exact CI material without introducing another authority artifact."""
    digest = compute_deployment_bundle_digest(
        decision=decision,
        change_set=change_set,
        release_plan=release_plan,
        version_resolution=version_resolution,
        release_snapshot=release_snapshot,
        deployment_plan=deployment_plan,
        review_preview=review_preview,
    )
    return DeploymentBundle(
        bundle_digest=digest,
        decision=decision,
        change_set=change_set,
        release_plan=release_plan,
        version_resolution=version_resolution,
        release_snapshot=release_snapshot,
        deployment_plan=deployment_plan,
        review_preview=review_preview,
    )


def compute_deployment_bundle_digest(
    *,
    decision: GovernanceDecision,
    change_set: ChangeSet,
    release_plan: ReleasePlan,
    version_resolution: VersionResolution,
    release_snapshot: ReleaseSnapshot,
    deployment_plan: DeploymentPlan,
    review_preview: DeploymentPreview,
    bundle_version: str = "1",
) -> str:
    """Return a content digest suitable for CI artifact pinning and approval evidence."""
    payload = {
        "bundle_version": bundle_version,
        "decision": decision.model_dump(mode="json"),
        "change_set": change_set.model_dump(mode="json"),
        "release_plan": release_plan.model_dump(mode="json"),
        "version_resolution": version_resolution.model_dump(mode="json"),
        "release_snapshot": release_snapshot.model_dump(mode="json"),
        "deployment_plan": deployment_plan.model_dump(mode="json"),
        "review_preview": review_preview.model_dump(mode="json"),
    }
    encoded = canonical_compact_json(payload).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
