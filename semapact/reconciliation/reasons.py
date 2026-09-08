"""Stable machine-readable reason vocabulary for runtime reconciliation.

Runtime reason codes are a thin public semantic projection of deterministic raw
reconciliation evidence. They remain separate from governance policy outcomes.
"""

from __future__ import annotations

from enum import Enum


class RuntimeReasonCode(str, Enum):
    """Stable machine-readable identifiers for supported runtime differences."""

    RUNTIME_SCHEMA_ADDED = "RUNTIME_SCHEMA_ADDED"
    RUNTIME_SCHEMA_REMOVED = "RUNTIME_SCHEMA_REMOVED"
    RUNTIME_PROPERTY_ADDED = "RUNTIME_PROPERTY_ADDED"
    RUNTIME_PROPERTY_REMOVED = "RUNTIME_PROPERTY_REMOVED"
    RUNTIME_PHYSICAL_TYPE_CHANGED = "RUNTIME_PHYSICAL_TYPE_CHANGED"
    RUNTIME_REQUIRED_CHANGED = "RUNTIME_REQUIRED_CHANGED"
