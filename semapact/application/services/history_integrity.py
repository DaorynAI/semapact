"""Application orchestration for governance-history integrity checks."""

from __future__ import annotations

from semapact.application.models.history_integrity import HistoryIntegrityReport
from semapact.application.services.evolution import EvolutionChainService
from semapact.history import HistoryIntegrityRepository


class HistoryIntegrityService:
    """Fail closed on physical corruption before validating logical history links."""

    def __init__(
        self,
        *,
        storage: HistoryIntegrityRepository,
        evolution: EvolutionChainService,
    ) -> None:
        self._storage = storage
        self._evolution = evolution

    def check_contract(self, contract_id: str) -> HistoryIntegrityReport:
        """Check repository storage first, then reuse evolution reference validation."""
        contract_id = _required_text(contract_id, "contract_id")
        storage_issues = self._storage.inspect_history_integrity()
        if storage_issues:
            return HistoryIntegrityReport(
                contract_id=contract_id,
                storage_issues=storage_issues,
                references_checked=False,
            )

        evolution = self._evolution.reconstruct(contract_id)
        return HistoryIntegrityReport(
            contract_id=contract_id,
            broken_references=evolution.broken_references,
            references_checked=True,
        )


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be str")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty")
    return cleaned
