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
from semapact.deployment import (
    DeploymentPlan,
    DeploymentPreview,
    DeploymentSourceSnapshot,
)
from semapact.governance import GovernanceDecision
from semapact.reconciliation import ReconciliationResult, RuntimeDriftStatus
from semapact.utils.deterministic import canonical_compact_json


class DeploymentExecutionResult(BaseModel):
    """Application result for one bundle-driven CD execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle_digest: str
    deployment_plan_id: str
    authorization_id: str
    release_record_id: str | None = None
    fresh_preview: DeploymentPreview
    reconciliation: ReconciliationResult
    status: RuntimeDriftStatus
    review_preview_changed: bool


class DeploymentBundle(BaseModel):
    """Immutable CI-to-CD package for candidate or formal release deployment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle_digest: str
    release: bool
    decision: GovernanceDecision
    change_set: ChangeSet
    deployment_source: DeploymentSourceSnapshot
    deployment_plan: DeploymentPlan
    review_preview: DeploymentPreview
    release_plan: ReleasePlan | None = None
    version_resolution: VersionResolution | None = None
    release_snapshot: ReleaseSnapshot | None = None
    bundle_version: Literal["2"] = "2"

    @model_validator(mode="after")
    def _validate_bundle_links(self) -> "DeploymentBundle":
        if self.change_set.contract_id != self.decision.contract_id:
            raise ValueError("DeploymentBundle decision/change-set contract mismatch")
        if self.deployment_source.contract_id != self.decision.contract_id:
            raise ValueError("DeploymentBundle source/decision contract mismatch")
        if self.deployment_source.release is not self.release:
            raise ValueError("DeploymentBundle source release mode mismatch")

        if self.release:
            if (
                self.release_plan is None
                or self.version_resolution is None
                or self.release_snapshot is None
            ):
                raise ValueError(
                    "Release DeploymentBundle requires release planning artifacts"
                )
            if self.release_plan.change_set_id != self.change_set.change_set_id:
                raise ValueError(
                    "DeploymentBundle release plan does not match ChangeSet"
                )
            if self.release_plan.decision_id != self.decision.decision_id:
                raise ValueError(
                    "DeploymentBundle release plan does not match decision"
                )
            if (
                self.version_resolution.release_plan_id
                != self.release_plan.release_plan_id
            ):
                raise ValueError(
                    "DeploymentBundle version resolution does not match ReleasePlan"
                )
            if self.release_snapshot.decision_id != self.decision.decision_id:
                raise ValueError("DeploymentBundle snapshot does not match decision")
            if self.release_snapshot.change_set_id != self.change_set.change_set_id:
                raise ValueError("DeploymentBundle snapshot does not match ChangeSet")
            if (
                self.release_snapshot.release_plan_id
                != self.release_plan.release_plan_id
            ):
                raise ValueError(
                    "DeploymentBundle snapshot does not match ReleasePlan"
                )
            if (
                self.release_snapshot.version_resolution_id
                != self.version_resolution.version_resolution_id
            ):
                raise ValueError(
                    "DeploymentBundle snapshot does not match VersionResolution"
                )
            if self.deployment_source.release_id != self.release_snapshot.release_snapshot_id:
                raise ValueError(
                    "DeploymentBundle deployment source does not match ReleaseSnapshot"
                )
        elif any(
            item is not None
            for item in (
                self.release_plan,
                self.version_resolution,
                self.release_snapshot,
            )
        ):
            raise ValueError(
                "Non-release DeploymentBundle must not contain release artifacts"
            )

        plan = self.deployment_plan
        if plan.source_snapshot_id != self.deployment_source.source_snapshot_id:
            raise ValueError(
                "DeploymentBundle plan does not match deployment source"
            )
        if plan.contract_id != self.deployment_source.contract_id:
            raise ValueError("DeploymentBundle plan/source contract mismatch")
        if plan.revision_ref != self.deployment_source.revision_ref:
            raise ValueError("DeploymentBundle plan/source revision mismatch")
        if plan.contract_version != self.deployment_source.contract_version:
            raise ValueError("DeploymentBundle plan/source version mismatch")
        if plan.release is not self.release:
            raise ValueError("DeploymentBundle plan release mode mismatch")

        if self.review_preview.deployment_plan_id != plan.deployment_plan_id:
            raise ValueError("DeploymentBundle preview does not match DeploymentPlan")

        expected = compute_deployment_bundle_digest(
            release=self.release,
            decision=self.decision,
            change_set=self.change_set,
            deployment_source=self.deployment_source,
            deployment_plan=self.deployment_plan,
            review_preview=self.review_preview,
            release_plan=self.release_plan,
            version_resolution=self.version_resolution,
            release_snapshot=self.release_snapshot,
            bundle_version=self.bundle_version,
        )
        if self.bundle_digest != expected:
            raise ValueError("DeploymentBundle digest does not match content")
        return self

def build_deployment_bundle(
    *,
    release: bool,
    decision: GovernanceDecision,
    change_set: ChangeSet,
    deployment_source: DeploymentSourceSnapshot,
    deployment_plan: DeploymentPlan,
    review_preview: DeploymentPreview,
    release_plan: ReleasePlan | None = None,
    version_resolution: VersionResolution | None = None,
    release_snapshot: ReleaseSnapshot | None = None,
) -> DeploymentBundle:
    """Package exact CI material without introducing another authority artifact."""
    digest = compute_deployment_bundle_digest(
        release=release,
        decision=decision,
        change_set=change_set,
        deployment_source=deployment_source,
        deployment_plan=deployment_plan,
        review_preview=review_preview,
        release_plan=release_plan,
        version_resolution=version_resolution,
        release_snapshot=release_snapshot,
    )
    return DeploymentBundle(
        bundle_digest=digest,
        release=release,
        decision=decision,
        change_set=change_set,
        deployment_source=deployment_source,
        deployment_plan=deployment_plan,
        review_preview=review_preview,
        release_plan=release_plan,
        version_resolution=version_resolution,
        release_snapshot=release_snapshot,
    )


def compute_deployment_bundle_digest(
    *,
    release: bool,
    decision: GovernanceDecision,
    change_set: ChangeSet,
    deployment_source: DeploymentSourceSnapshot,
    deployment_plan: DeploymentPlan,
    review_preview: DeploymentPreview,
    release_plan: ReleasePlan | None = None,
    version_resolution: VersionResolution | None = None,
    release_snapshot: ReleaseSnapshot | None = None,
    bundle_version: str = "2",
) -> str:
    """Return the immutable CI artifact digest for candidate or release deployment."""
    payload = {
        "bundle_version": bundle_version,
        "release": release,
        "decision": decision.model_dump(mode="json"),
        "change_set": change_set.model_dump(mode="json"),
        "deployment_source": deployment_source.model_dump(mode="json"),
        "deployment_plan": deployment_plan.model_dump(mode="json"),
        "review_preview": review_preview.model_dump(mode="json"),
        "release_plan": (
            release_plan.model_dump(mode="json")
            if release_plan is not None
            else None
        ),
        "version_resolution": (
            version_resolution.model_dump(mode="json")
            if version_resolution is not None
            else None
        ),
        "release_snapshot": (
            release_snapshot.model_dump(mode="json")
            if release_snapshot is not None
            else None
        ),
    }
    encoded = canonical_compact_json(payload).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
