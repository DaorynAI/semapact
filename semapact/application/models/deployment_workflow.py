"""Application artifacts for target-specific deployment workflows."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from semapact.contractops import ChangeSet, ContractRelease
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
    contract_release_id: str | None = None
    fresh_preview: DeploymentPreview
    reconciliation: ReconciliationResult
    status: RuntimeDriftStatus
    review_preview_changed: bool


class DeploymentBundle(BaseModel):
    """Immutable target-specific CI-to-CD deployment package.

    Candidate versus formal-release mode is derived from deployment_source.
    The bundle never stores a second mode flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle_digest: str
    deployment_source: DeploymentSourceSnapshot
    deployment_plan: DeploymentPlan
    review_preview: DeploymentPreview
    decision: GovernanceDecision | None = None
    change_set: ChangeSet | None = None
    contract_release: ContractRelease | None = None
    bundle_version: Literal["1"] = "1"

    @property
    def is_release(self) -> bool:
        return self.deployment_source.source_kind == "contract_release"

    @model_validator(mode="after")
    def _validate_bundle_links(self) -> "DeploymentBundle":
        source = self.deployment_source
        plan = self.deployment_plan

        if self.is_release:
            if self.contract_release is None:
                raise ValueError(
                    "Release DeploymentBundle requires finalized ContractRelease"
                )
            if self.decision is not None or self.change_set is not None:
                raise ValueError(
                    "Release DeploymentBundle must not carry candidate governance artifacts"
                )
            release = self.contract_release
            if source.release_id != release.contract_release_id:
                raise ValueError(
                    "DeploymentBundle source does not reference ContractRelease"
                )
            if source.contract_id != release.contract_id:
                raise ValueError(
                    "DeploymentBundle source/release contract mismatch"
                )
            if source.contract_version != release.contract_version:
                raise ValueError(
                    "DeploymentBundle source/release version mismatch"
                )
            if source.revision_ref != release.source_revision_ref:
                raise ValueError(
                    "DeploymentBundle source/release revision mismatch"
                )
        else:
            if source.source_kind != "candidate":
                raise ValueError(
                    "Canonical DeploymentBundle supports candidate or finalized ContractRelease sources"
                )
            if self.decision is None or self.change_set is None:
                raise ValueError(
                    "Candidate DeploymentBundle requires decision and ChangeSet"
                )
            if self.contract_release is not None:
                raise ValueError(
                    "Candidate DeploymentBundle cannot contain ContractRelease"
                )
            if self.change_set.contract_id != self.decision.contract_id:
                raise ValueError(
                    "DeploymentBundle decision/change-set contract mismatch"
                )
            if source.contract_id != self.decision.contract_id:
                raise ValueError(
                    "DeploymentBundle source/decision contract mismatch"
                )
            if self.change_set.candidate_revision_ref != source.revision_ref:
                raise ValueError(
                    "DeploymentBundle candidate revision does not match ChangeSet"
                )
            if self.change_set.changes != self.decision.changes:
                raise ValueError(
                    "DeploymentBundle decision/change-set changes mismatch"
                )

        if plan.source_snapshot_id != source.source_snapshot_id:
            raise ValueError(
                "DeploymentBundle plan does not match deployment source"
            )
        if plan.contract_id != source.contract_id:
            raise ValueError("DeploymentBundle plan/source contract mismatch")
        if plan.revision_ref != source.revision_ref:
            raise ValueError("DeploymentBundle plan/source revision mismatch")
        if plan.contract_version != source.contract_version:
            raise ValueError("DeploymentBundle plan/source version mismatch")
        if self.review_preview.deployment_plan_id != plan.deployment_plan_id:
            raise ValueError("DeploymentBundle preview does not match DeploymentPlan")

        expected = compute_deployment_bundle_digest(
            deployment_source=source,
            deployment_plan=plan,
            review_preview=self.review_preview,
            decision=self.decision,
            change_set=self.change_set,
            contract_release=self.contract_release,
            bundle_version=self.bundle_version,
        )
        if self.bundle_digest != expected:
            raise ValueError("DeploymentBundle digest does not match content")
        return self


def build_deployment_bundle(
    *,
    deployment_source: DeploymentSourceSnapshot,
    deployment_plan: DeploymentPlan,
    review_preview: DeploymentPreview,
    decision: GovernanceDecision | None = None,
    change_set: ChangeSet | None = None,
    contract_release: ContractRelease | None = None,
) -> DeploymentBundle:
    """Package exact target-specific deployment material without release planning."""
    digest = compute_deployment_bundle_digest(
        deployment_source=deployment_source,
        deployment_plan=deployment_plan,
        review_preview=review_preview,
        decision=decision,
        change_set=change_set,
        contract_release=contract_release,
    )
    return DeploymentBundle(
        bundle_digest=digest,
        deployment_source=deployment_source,
        deployment_plan=deployment_plan,
        review_preview=review_preview,
        decision=decision,
        change_set=change_set,
        contract_release=contract_release,
    )


def compute_deployment_bundle_digest(
    *,
    deployment_source: DeploymentSourceSnapshot,
    deployment_plan: DeploymentPlan,
    review_preview: DeploymentPreview,
    decision: GovernanceDecision | None = None,
    change_set: ChangeSet | None = None,
    contract_release: ContractRelease | None = None,
    bundle_version: str = "1",
) -> str:
    """Return the immutable digest for one target-specific deployment bundle."""
    payload = {
        "bundle_version": bundle_version,
        "deployment_source": deployment_source.model_dump(mode="json"),
        "deployment_plan": deployment_plan.model_dump(mode="json"),
        "review_preview": review_preview.model_dump(mode="json"),
        "decision": decision.model_dump(mode="json") if decision is not None else None,
        "change_set": change_set.model_dump(mode="json") if change_set is not None else None,
        "contract_release": (
            contract_release.model_dump(mode="json")
            if contract_release is not None
            else None
        ),
    }
    encoded = canonical_compact_json(payload).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
