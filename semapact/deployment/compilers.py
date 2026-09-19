"""Provider-neutral compiler contract for schema transitions."""

from __future__ import annotations

from abc import ABC, abstractmethod

from semapact.deployment.models import NativeOperation
from semapact.deployment.schema_transitions import SchemaTransition
from semapact.exceptions import ValidationError
from semapact.schema import SchemaPropertyState


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



def require_native_definition(column: SchemaPropertyState) -> str:
    """Return one canonical target-compiler definition or fail closed."""
    definition = column.native_definition
    if definition is None or not definition.strip():
        raise ValidationError(
            "Transition compilation requires target-compiler output for "
            f"column '{column.identity}'"
        )
    return definition
