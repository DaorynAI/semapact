"""Provider contracts for generic deployment orchestration."""

from __future__ import annotations

from abc import ABC, abstractmethod

from open_data_contract_standard.model import SchemaObject
from pydantic import BaseModel, ConfigDict, field_validator

from semapact.deployment.compilers import TransitionCompiler
from semapact.deployment.models import DeploymentTarget, NativeOperation
from semapact.deployment.schema_transitions import SchemaTransitionPlanner
from semapact.observation.models import ObservedAsset
from semapact.observation.providers import RuntimeProvider
from semapact.schema import SchemaAssetState, SchemaMapper



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


class DeploymentPlatform(ABC):
    """Minimal platform seam consumed by the generic deployment orchestrator."""

    key: str
    schema_mapper: SchemaMapper
    transition_planner: SchemaTransitionPlanner
    transition_compiler: TransitionCompiler
    runtime_provider: RuntimeProvider

    @abstractmethod
    def validate_target(self, target: DeploymentTarget) -> None:
        """Validate provider-local deployment target syntax/constraints."""
        raise NotImplementedError

    @abstractmethod
    def validate_desired_asset(
        self,
        *,
        target: DeploymentTarget,
        physical_name: str,
        desired: SchemaObject,
        mapped: SchemaAssetState,
    ) -> None:
        """Validate provider-specific desired-state constraints."""
        raise NotImplementedError

    @abstractmethod
    def validate_observed_asset(
        self,
        *,
        target: DeploymentTarget,
        physical_name: str,
        observed: ObservedAsset,
    ) -> None:
        """Validate provider-specific observed runtime constraints."""
        raise NotImplementedError
