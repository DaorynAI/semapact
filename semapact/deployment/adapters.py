"""Replaceable write-side deployment adapter boundary."""

from __future__ import annotations

from abc import ABC, abstractmethod

from semapact.deployment.models import (
    DeploymentAuthorization,
    DeploymentPlan,
    DeploymentPreview,
)


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
    def execute(
        self,
        plan: DeploymentPlan,
        preview: DeploymentPreview,
        authorization: DeploymentAuthorization,
    ) -> None:
        """Execute only the exact authorized preview."""
        raise NotImplementedError
