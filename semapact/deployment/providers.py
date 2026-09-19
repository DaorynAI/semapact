"""Provider contracts for generic deployment orchestration."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict, field_validator

from semapact.deployment.models import NativeOperation



class DeploymentExecutionConfig(BaseModel):
    """Typed provider execution configuration passed through composition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    platform: str

    @field_validator("platform")
    @classmethod
    def _normalize_platform(cls, value: str) -> str:
        cleaned = value.strip().casefold()
        if not cleaned:
            raise ValueError("platform must not be empty")
        return cleaned


class NativeOperationExecutor(ABC):
    """Execute one provider-native operation."""

    key: str

    @abstractmethod
    def execute(self, operation: NativeOperation) -> None:
        """Execute one exact native operation."""
        raise NotImplementedError

