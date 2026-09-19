"""Platform-neutral reconciliation result models.

Reconciliation reports raw desired-vs-observed differences with a stable runtime
reason code. It does not infer drift cause, deployment state, or governance status;
those concerns remain separate downstream layers.
"""

from __future__ import annotations

import json
from enum import Enum

from pydantic import BaseModel, ConfigDict

from semapact.schema import SchemaDifferenceType, SchemaSubject


class ReconciliationModel(BaseModel):
    """Shared immutable base for reconciliation models."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# Backward-compatible public names projected from the shared schema comparator.
ReconciliationDifferenceType = SchemaDifferenceType
ReconciliationSubject = SchemaSubject


class RuntimeReasonCode(str, Enum):
    """Stable semantic identifiers projected from supported raw differences."""

    RUNTIME_SCHEMA_ADDED = "RUNTIME_SCHEMA_ADDED"
    RUNTIME_SCHEMA_REMOVED = "RUNTIME_SCHEMA_REMOVED"
    RUNTIME_PROPERTY_ADDED = "RUNTIME_PROPERTY_ADDED"
    RUNTIME_PROPERTY_REMOVED = "RUNTIME_PROPERTY_REMOVED"
    RUNTIME_PHYSICAL_TYPE_CHANGED = "RUNTIME_PHYSICAL_TYPE_CHANGED"
    RUNTIME_REQUIRED_CHANGED = "RUNTIME_REQUIRED_CHANGED"


class ReconciliationDifference(ReconciliationModel):
    """One deterministic difference between governed and observed state."""

    difference_type: SchemaDifferenceType
    subject: SchemaSubject
    reason_code: RuntimeReasonCode
    path: str
    asset_identity: str
    property_identity: str | None = None
    expected: str | bool | None = None
    observed: str | bool | None = None


class ReconciliationResult(ReconciliationModel):
    """Governed desired-vs-observed comparison result."""

    contract_id: str
    contract_version: str
    observation_source_identifier: str
    observation_fingerprint: str
    differences: tuple[ReconciliationDifference, ...] = ()
    unverified_paths: tuple[str, ...] = ()

    @property
    def has_differences(self) -> bool:
        """Return whether any runtime differences were found."""
        return bool(self.differences)

    @property
    def comparison_complete(self) -> bool:
        """Return whether every governed comparison could be verified."""
        return not self.unverified_paths


def serialize_reconciliation_result(result: ReconciliationResult) -> str:
    """Serialize a reconciliation result deterministically for machine use."""
    return json.dumps(
        result.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
