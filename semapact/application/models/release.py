"""Application result models for canonical release orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from semapact.contractops import ChangeSet, ReleasePlan, VersionResolution
from semapact.governance import GovernanceDecision


@dataclass(frozen=True)
class ReleasePlanningResult:
    """Exact canonical artifacts produced by one release planning pass."""

    change_set: ChangeSet
    decision: GovernanceDecision
    release_plan: ReleasePlan
    version_resolution: VersionResolution
