"""Replaceable write-side deployment adapter boundary."""

from __future__ import annotations

from abc import ABC, abstractmethod

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.deployment.models import (
    DeploymentAssessment,
    DeploymentAuthorization,
    DeploymentPlan,
    DeploymentPreview,
    DeploymentTarget,
)
from semapact.reconciliation import ReconciliationResult


class DeploymentAdapter(ABC):
    """Own the complete provider-neutral deployment lifecycle entrypoints."""

    key: str

    def assess(
        self,
        contract: OpenDataContractStandard,
        *,
        candidate_revision_ref: str,
        target: DeploymentTarget,
    ) -> DeploymentAssessment:
        """Observe runtime and assess one candidate without creating execution authority."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support candidate deployment assessment"
        )

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
    def execute(
        self,
        plan: DeploymentPlan,
        preview: DeploymentPreview,
        authorization: DeploymentAuthorization,
    ) -> None:
        """Execute only the exact authorized preview."""
        raise NotImplementedError
