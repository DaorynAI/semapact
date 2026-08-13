"""Backward-compatible import path for governance reason vocabulary.

New code should import from ``semapact.constants.governance_reasons`` or the public
``semapact.governance`` API. This module contains no definitions of its own.
"""

from semapact.constants.governance_reasons import (
    GOVERNANCE_REASON_REGISTRY,
    GovernanceReasonCode,
    GovernanceReasonDefinition,
    GovernanceSeverity,
    reason_severity,
)

__all__ = [
    "GovernanceReasonCode",
    "GovernanceSeverity",
    "GovernanceReasonDefinition",
    "GOVERNANCE_REASON_REGISTRY",
    "reason_severity",
]
