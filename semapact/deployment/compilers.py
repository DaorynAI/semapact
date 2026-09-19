"""Provider-neutral compiler contract for schema transitions."""

from __future__ import annotations

from typing import Protocol

from semapact.deployment.models import NativeOperation
from semapact.deployment.schema_transitions import SchemaTransition


class TransitionCompiler(Protocol):
    """Compile one semantic schema transition into a provider-native operation."""

    key: str

    def compile(
        self,
        *,
        runtime_target: str,
        transition: SchemaTransition,
    ) -> NativeOperation: ...
