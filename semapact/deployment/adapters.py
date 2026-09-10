"""Replaceable write-side deployment adapter boundary."""

from __future__ import annotations

from typing import Protocol

from semapact.deployment.models import (
    DeploymentAuthorization,
    DeploymentPlan,
    DeploymentPreview,
)
from semapact.observation.models import ObservedPlatformState


class DeploymentAdapter(Protocol):
    """Translate and execute one exact DeploymentPlan for a runtime provider."""

    key: str

    def validate(self, plan: DeploymentPlan) -> None: ...

    def preview(
        self,
        plan: DeploymentPlan,
        observed_state: ObservedPlatformState,
    ) -> DeploymentPreview: ...

    def execute(
        self,
        plan: DeploymentPlan,
        preview: DeploymentPreview,
        authorization: DeploymentAuthorization,
    ) -> None: ...
