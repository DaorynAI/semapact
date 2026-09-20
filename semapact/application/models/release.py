"""Application artifacts for target-neutral contract release workflows."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from semapact.contractops import ChangeSet, ReleasePlan, ReleaseSnapshot, VersionResolution
from semapact.governance import GovernanceDecision
from semapact.utils.deterministic import canonical_compact_json


@dataclass(frozen=True)
class ReleasePlanningResult:
    """Exact canonical artifacts produced by one release planning pass."""

    change_set: ChangeSet
    decision: GovernanceDecision
    release_plan: ReleasePlan
    version_resolution: VersionResolution


class ReleaseBundle(BaseModel):
    """Immutable target-neutral CI artifact for one formal contract release."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle_digest: str
    decision: GovernanceDecision
    change_set: ChangeSet
    release_plan: ReleasePlan
    version_resolution: VersionResolution
    release_snapshot: ReleaseSnapshot
    bundle_version: Literal["1"] = "1"

    @model_validator(mode="after")
    def _validate_links(self) -> "ReleaseBundle":
        if self.change_set.contract_id != self.decision.contract_id:
            raise ValueError("ReleaseBundle decision/change-set contract mismatch")
        if self.release_plan.change_set_id != self.change_set.change_set_id:
            raise ValueError("ReleaseBundle release plan does not match ChangeSet")
        if self.release_plan.decision_id != self.decision.decision_id:
            raise ValueError("ReleaseBundle release plan does not match decision")
        if self.version_resolution.release_plan_id != self.release_plan.release_plan_id:
            raise ValueError(
                "ReleaseBundle version resolution does not match ReleasePlan"
            )
        snapshot = self.release_snapshot
        if snapshot.decision_id != self.decision.decision_id:
            raise ValueError("ReleaseBundle snapshot does not match decision")
        if snapshot.change_set_id != self.change_set.change_set_id:
            raise ValueError("ReleaseBundle snapshot does not match ChangeSet")
        if snapshot.release_plan_id != self.release_plan.release_plan_id:
            raise ValueError("ReleaseBundle snapshot does not match ReleasePlan")
        if (
            snapshot.version_resolution_id
            != self.version_resolution.version_resolution_id
        ):
            raise ValueError(
                "ReleaseBundle snapshot does not match VersionResolution"
            )
        expected = compute_release_bundle_digest(
            decision=self.decision,
            change_set=self.change_set,
            release_plan=self.release_plan,
            version_resolution=self.version_resolution,
            release_snapshot=self.release_snapshot,
            bundle_version=self.bundle_version,
        )
        if self.bundle_digest != expected:
            raise ValueError("ReleaseBundle digest does not match content")
        return self


def build_release_bundle(
    *,
    decision: GovernanceDecision,
    change_set: ChangeSet,
    release_plan: ReleasePlan,
    version_resolution: VersionResolution,
    release_snapshot: ReleaseSnapshot,
) -> ReleaseBundle:
    """Build the exact target-neutral release artifact reviewed by CI/CD."""
    digest = compute_release_bundle_digest(
        decision=decision,
        change_set=change_set,
        release_plan=release_plan,
        version_resolution=version_resolution,
        release_snapshot=release_snapshot,
    )
    return ReleaseBundle(
        bundle_digest=digest,
        decision=decision,
        change_set=change_set,
        release_plan=release_plan,
        version_resolution=version_resolution,
        release_snapshot=release_snapshot,
    )


def compute_release_bundle_digest(
    *,
    decision: GovernanceDecision,
    change_set: ChangeSet,
    release_plan: ReleasePlan,
    version_resolution: VersionResolution,
    release_snapshot: ReleaseSnapshot,
    bundle_version: str = "1",
) -> str:
    """Return the immutable digest for one target-neutral release bundle."""
    payload = {
        "bundle_version": bundle_version,
        "decision": decision.model_dump(mode="json"),
        "change_set": change_set.model_dump(mode="json"),
        "release_plan": release_plan.model_dump(mode="json"),
        "version_resolution": version_resolution.model_dump(mode="json"),
        "release_snapshot": release_snapshot.model_dump(mode="json"),
    }
    encoded = canonical_compact_json(payload).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
