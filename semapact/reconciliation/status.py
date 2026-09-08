"""Conservative platform-neutral classification of reconciliation outcomes."""

from __future__ import annotations

from enum import Enum

from semapact.reconciliation.models import ReconciliationResult


class RuntimeDriftStatus(str, Enum):
    """Operational state that can be proven from M1 reconciliation evidence."""

    IN_SYNC = "IN_SYNC"
    DRIFT = "DRIFT"
    INDETERMINATE = "INDETERMINATE"


def classify_reconciliation_status(result: ReconciliationResult) -> RuntimeDriftStatus:
    """Classify reconciliation without inferring deployment history or causality."""
    if result.differences:
        return RuntimeDriftStatus.DRIFT
    if result.unverified_paths:
        return RuntimeDriftStatus.INDETERMINATE
    return RuntimeDriftStatus.IN_SYNC
