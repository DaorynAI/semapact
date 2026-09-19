"""Application result models for contract-first deployment workflows."""

from __future__ import annotations

from dataclasses import dataclass

from semapact.application.models.release import ReleasePlanningResult
from semapact.deployment import DeploymentAssessment


@dataclass(frozen=True)
class DeploymentWorkflowAssessment:
    """Read-only governance + runtime assessment for one candidate revision."""

    release: ReleasePlanningResult
    deployment: DeploymentAssessment
