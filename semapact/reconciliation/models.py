"""Platform-neutral reconciliation result models.

Reconciliation reports raw desired-vs-observed differences. It does not infer
drift cause, deployment state, or governance status; those classifications are
separate downstream concerns.
"""

from __future__ import annotations

import json
from enum import Enum

from pydantic import BaseModel, ConfigDict


class ReconciliationModel(BaseModel):
    """Shared immutable base for reconciliation models."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ReconciliationDifferenceType(str, Enum):
    """Generic raw comparison operation, not a public reason-code taxonomy."""

    MISSING = "missing"
    UNEXPECTED = "unexpected"
    MISMATCH = "mismatch"


class ReconciliationSubject(str, Enum):
    """Comparable subject represented by a raw reconciliation difference."""

    ASSET = "asset"
    PROPERTY = "property"
    PHYSICAL_TYPE = "physical_type"
    NULLABILITY = "nullability"


class ReconciliationDifference(ReconciliationModel):
    """One deterministic raw difference between desired and observed state."""

    difference_type: ReconciliationDifferenceType
    subject: ReconciliationSubject
    path: str
    asset_identity: str
    property_identity: str | None = None
    expected: str | bool | None = None
    observed: str | bool | None = None


class ReconciliationResult(ReconciliationModel):
    """Raw desired-vs-observed comparison result."""

    contract_id: str
    contract_version: str
    observation_source_identifier: str
    observation_fingerprint: str
    differences: tuple[ReconciliationDifference, ...] = ()

    @property
    def has_differences(self) -> bool:
        """Return whether any raw differences were found."""
        return bool(self.differences)


def serialize_reconciliation_result(result: ReconciliationResult) -> str:
    """Serialize a reconciliation result deterministically for machine use."""
    return json.dumps(
        result.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
