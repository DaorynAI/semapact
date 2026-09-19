"""Provider contracts for generic deployment orchestration."""

from __future__ import annotations

from abc import ABC, abstractmethod

from open_data_contract_standard.model import SchemaObject

from semapact.deployment.compilers import TransitionCompiler
from semapact.deployment.models import DeploymentTarget, NativeOperation
from semapact.observation.models import ObservedAsset
from semapact.observation.providers import RuntimeProvider
from semapact.schema import SchemaAssetState, SchemaMapper


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
