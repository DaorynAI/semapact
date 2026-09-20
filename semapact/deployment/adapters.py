"""Replaceable write-side deployment adapter boundary."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from semapact.deployment.models import (
    DeploymentPlan,
    DeploymentPreview,
)
from semapact.reconciliation import ReconciliationResult





@dataclass(frozen=True)
class RuntimeReleaseMetadata:
    """Release provenance projected into a runtime provider after convergence."""

    contract_id: str
    contract_version: str
    contract_release_id: str
    source_revision_ref: str


@runtime_checkable
class RuntimeReleaseMetadataProjector(Protocol):
    """Optional provider capability for projecting formal release provenance."""

    def project_release_metadata(
        self,
        plan: DeploymentPlan,
        metadata: RuntimeReleaseMetadata,
    ) -> None: ...

class DeploymentAdapter(ABC):
    """Own the complete provider-neutral deployment lifecycle entrypoints."""

    key: str

    @abstractmethod
    def validate(self, plan: DeploymentPlan) -> None:
        """Validate one exact DeploymentPlan."""
        raise NotImplementedError

    @abstractmethod
    def preview(self, plan: DeploymentPlan) -> DeploymentPreview:
        """Observe current runtime and derive the exact deployment preview."""
        raise NotImplementedError

    @abstractmethod
    def verify(self, plan: DeploymentPlan) -> ReconciliationResult:
        """Observe runtime and verify convergence for one exact plan."""
        raise NotImplementedError

    @abstractmethod
    def apply(
        self,
        plan: DeploymentPlan,
        preview: DeploymentPreview,
    ) -> None:
        """Apply one exact preview after the application boundary authorizes execution."""
        raise NotImplementedError
