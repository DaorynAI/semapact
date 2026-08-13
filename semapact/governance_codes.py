"""Stable public governance reason-code registry.

This module is intentionally dependency-light so lifecycle policy and the governance
kernel can share the same machine-readable reason contract without introducing an
import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class GovernanceSeverity(str, Enum):
    """Stable severity levels attached to governance reasons."""

    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class GovernanceReasonCode(str, Enum):
    """Stable machine-readable identifiers for governance conditions."""

    CONTRACT_ID_CHANGED = "CONTRACT_ID_CHANGED"
    CONTRACT_VERSION_MANUALLY_CHANGED = "CONTRACT_VERSION_MANUALLY_CHANGED"
    SCHEMA_REMOVED = "SCHEMA_REMOVED"
    PROPERTY_REMOVED = "PROPERTY_REMOVED"
    RELATIONSHIP_REMOVED = "RELATIONSHIP_REMOVED"
    LOGICAL_TYPE_CHANGED = "LOGICAL_TYPE_CHANGED"
    PHYSICAL_TYPE_NARROWED = "PHYSICAL_TYPE_NARROWED"
    DECIMAL_PRECISION_REDUCED = "DECIMAL_PRECISION_REDUCED"
    DECIMAL_SCALE_REDUCED = "DECIMAL_SCALE_REDUCED"
    REQUIRED_TIGHTENED = "REQUIRED_TIGHTENED"
    ENUM_VALUES_REMOVED = "ENUM_VALUES_REMOVED"
    RETIRED_CONTRACT_MODIFIED = "RETIRED_CONTRACT_MODIFIED"
    CONTRACT_RETIRED_TRANSITION = "CONTRACT_RETIRED_TRANSITION"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    MERGE_CONFLICT = "MERGE_CONFLICT"
    CHANGE_ASSESSMENT = "CHANGE_ASSESSMENT"


@dataclass(frozen=True, slots=True)
class GovernanceReasonDefinition:
    """Public semantics for one stable governance reason code."""

    severity: GovernanceSeverity
    description: str


_GOVERNANCE_REASON_REGISTRY = {
    GovernanceReasonCode.CONTRACT_ID_CHANGED: GovernanceReasonDefinition(
        GovernanceSeverity.ERROR,
        "The governed contract identity was changed.",
    ),
    GovernanceReasonCode.CONTRACT_VERSION_MANUALLY_CHANGED: GovernanceReasonDefinition(
        GovernanceSeverity.ERROR,
        "The release-managed contract version was changed outside the release flow.",
    ),
    GovernanceReasonCode.SCHEMA_REMOVED: GovernanceReasonDefinition(
        GovernanceSeverity.WARNING,
        "An in-scope schema was removed from an active contract.",
    ),
    GovernanceReasonCode.PROPERTY_REMOVED: GovernanceReasonDefinition(
        GovernanceSeverity.WARNING,
        "An in-scope property was removed from an active contract.",
    ),
    GovernanceReasonCode.RELATIONSHIP_REMOVED: GovernanceReasonDefinition(
        GovernanceSeverity.WARNING,
        "An in-scope relationship was removed from an active contract.",
    ),
    GovernanceReasonCode.LOGICAL_TYPE_CHANGED: GovernanceReasonDefinition(
        GovernanceSeverity.WARNING,
        "A governed property's logical type changed.",
    ),
    GovernanceReasonCode.PHYSICAL_TYPE_NARROWED: GovernanceReasonDefinition(
        GovernanceSeverity.WARNING,
        "A governed property's physical type narrowed.",
    ),
    GovernanceReasonCode.DECIMAL_PRECISION_REDUCED: GovernanceReasonDefinition(
        GovernanceSeverity.WARNING,
        "A governed decimal property's precision was reduced.",
    ),
    GovernanceReasonCode.DECIMAL_SCALE_REDUCED: GovernanceReasonDefinition(
        GovernanceSeverity.WARNING,
        "A governed decimal property's scale was reduced.",
    ),
    GovernanceReasonCode.REQUIRED_TIGHTENED: GovernanceReasonDefinition(
        GovernanceSeverity.WARNING,
        "A governed property changed from optional to required.",
    ),
    GovernanceReasonCode.ENUM_VALUES_REMOVED: GovernanceReasonDefinition(
        GovernanceSeverity.WARNING,
        "Allowed enum values were removed from a governed property.",
    ),
    GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED: GovernanceReasonDefinition(
        GovernanceSeverity.ERROR,
        "A retired contract was modified.",
    ),
    GovernanceReasonCode.CONTRACT_RETIRED_TRANSITION: GovernanceReasonDefinition(
        GovernanceSeverity.WARNING,
        "A contract was transitioned to retired and requires governance review.",
    ),
    GovernanceReasonCode.VALIDATION_FAILED: GovernanceReasonDefinition(
        GovernanceSeverity.ERROR,
        "Contract validation failed.",
    ),
    GovernanceReasonCode.MERGE_CONFLICT: GovernanceReasonDefinition(
        GovernanceSeverity.WARNING,
        "A deterministic metadata merge conflict requires review.",
    ),
    GovernanceReasonCode.CHANGE_ASSESSMENT: GovernanceReasonDefinition(
        GovernanceSeverity.INFO,
        "Version-bump classification evidence for the contract change.",
    ),
}

GOVERNANCE_REASON_REGISTRY: Mapping[
    GovernanceReasonCode, GovernanceReasonDefinition
] = MappingProxyType(_GOVERNANCE_REASON_REGISTRY)


def reason_severity(code: GovernanceReasonCode) -> GovernanceSeverity:
    """Return the canonical severity for a registered reason code."""

    return GOVERNANCE_REASON_REGISTRY[code].severity
