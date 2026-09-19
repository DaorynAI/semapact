"""Provider-neutral compiler contract for schema transitions."""

from __future__ import annotations

from abc import ABC, abstractmethod

from semapact.deployment.models import NativeOperation
from semapact.deployment.schema_transitions import SchemaTransition


class TransitionCompiler(ABC):
    """Compile one semantic schema transition into a provider-native operation."""

    key: str

    @abstractmethod
    def compile(
        self,
        *,
        runtime_target: str,
        transition: SchemaTransition,
    ) -> NativeOperation:
        """Compile one semantic transition into a provider-native operation."""
        raise NotImplementedError
