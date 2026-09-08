"""Stable machine-readable reason vocabulary for runtime reconciliation.

Runtime reason codes describe observed desired-vs-runtime differences. They are
read-side evidence and must remain separate from governance policy reason codes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class RuntimeDifferenceClassification(str, Enum):
    """Stable high-level classification for runtime differences."""

    STRUCTURAL = "STRUCTURAL"
    SEMANTIC = "SEMANTIC"


class RuntimeReasonCode(str, Enum):
    """Stable machine-readable identifiers for supported runtime differences."""

    RUNTIME_SCHEMA_ADDED = "RUNTIME_SCHEMA_ADDED"
    RUNTIME_SCHEMA_REMOVED = "RUNTIME_SCHEMA_REMOVED"
    RUNTIME_PROPERTY_ADDED = "RUNTIME_PROPERTY_ADDED"
    RUNTIME_PROPERTY_REMOVED = "RUNTIME_PROPERTY_REMOVED"
    RUNTIME_PHYSICAL_TYPE_CHANGED = "RUNTIME_PHYSICAL_TYPE_CHANGED"
    RUNTIME_REQUIRED_CHANGED = "RUNTIME_REQUIRED_CHANGED"


@dataclass(frozen=True, slots=True)
class RuntimeReasonDefinition:
    """Public semantics for one stable runtime reason code."""

    classification: RuntimeDifferenceClassification
    description: str


_RUNTIME_REASON_REGISTRY = {
    RuntimeReasonCode.RUNTIME_SCHEMA_ADDED: RuntimeReasonDefinition(
        RuntimeDifferenceClassification.STRUCTURAL,
        "Runtime contains an asset that is not present in the governed contract.",
    ),
    RuntimeReasonCode.RUNTIME_SCHEMA_REMOVED: RuntimeReasonDefinition(
        RuntimeDifferenceClassification.STRUCTURAL,
        "A governed asset is missing from runtime.",
    ),
    RuntimeReasonCode.RUNTIME_PROPERTY_ADDED: RuntimeReasonDefinition(
        RuntimeDifferenceClassification.STRUCTURAL,
        "Runtime contains a property that is not present in the governed contract.",
    ),
    RuntimeReasonCode.RUNTIME_PROPERTY_REMOVED: RuntimeReasonDefinition(
        RuntimeDifferenceClassification.STRUCTURAL,
        "A governed property is missing from runtime.",
    ),
    RuntimeReasonCode.RUNTIME_PHYSICAL_TYPE_CHANGED: RuntimeReasonDefinition(
        RuntimeDifferenceClassification.STRUCTURAL,
        "A runtime property's physical type differs from the governed contract.",
    ),
    RuntimeReasonCode.RUNTIME_REQUIRED_CHANGED: RuntimeReasonDefinition(
        RuntimeDifferenceClassification.STRUCTURAL,
        "A runtime property's nullability differs from the governed required state.",
    ),
}

RUNTIME_REASON_REGISTRY: Mapping[RuntimeReasonCode, RuntimeReasonDefinition] = (
    MappingProxyType(_RUNTIME_REASON_REGISTRY)
)


def runtime_reason_definition(code: RuntimeReasonCode) -> RuntimeReasonDefinition:
    """Return the canonical public definition for a runtime reason code."""

    return RUNTIME_REASON_REGISTRY[code]
