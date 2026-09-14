"""Application read model for governance-history integrity checks."""

from __future__ import annotations

from dataclasses import dataclass

from semapact.application.models.evolution import BrokenHistoryReference
from semapact.history import HistoryStorageIntegrityIssue


@dataclass(frozen=True)
class HistoryIntegrityReport:
    """Physical storage and logical-reference integrity for one contract check."""

    contract_id: str
    storage_issues: tuple[HistoryStorageIntegrityIssue, ...] = ()
    broken_references: tuple[BrokenHistoryReference, ...] = ()
    references_checked: bool = True

    @property
    def valid(self) -> bool:
        """Return whether both storage and reference integrity were proven clean."""
        return (
            self.references_checked
            and not self.storage_issues
            and not self.broken_references
        )
