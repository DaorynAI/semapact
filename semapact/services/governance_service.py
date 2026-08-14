"""Application service boundary for deterministic governance workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.change_context import ChangeContext
from semapact.governance.evaluator import evaluate_governance_decision
from semapact.governance.models import GovernanceDecision
from semapact.lifecycle.merge_engine import ContractMergeEngine, MergeConflict, MergeResult


@dataclass(frozen=True)
class GovernanceAnalysis:
    """One merge-and-governance analysis using a single resolved context."""

    context: ChangeContext
    merge_result: MergeResult
    decision: GovernanceDecision


class GovernanceService:
    """Own ChangeContext construction and delegate governance domain work."""

    def __init__(self, merge_engine: ContractMergeEngine | None = None) -> None:
        self._merge_engine = merge_engine or ContractMergeEngine()

    @staticmethod
    def create_context(effective_date: date | str) -> ChangeContext:
        """Resolve an interface/application date into the domain ChangeContext once."""
        if isinstance(effective_date, str):
            try:
                resolved_date = date.fromisoformat(effective_date)
            except ValueError as exc:
                raise ValueError("effective_date must use YYYY-MM-DD") from exc
        elif isinstance(effective_date, date):
            resolved_date = effective_date
        else:
            raise TypeError("effective_date must be a date or YYYY-MM-DD string")

        return ChangeContext(effective_date=resolved_date)

    def evaluate(
        self,
        base_contract: OpenDataContractStandard,
        candidate_contract: OpenDataContractStandard,
        *,
        effective_date: date | str,
        merge_conflicts: Sequence[MergeConflict] = (),
    ) -> GovernanceDecision:
        """Evaluate one contract change from an application-level effective date."""
        context = self.create_context(effective_date)
        return evaluate_governance_decision(
            base_contract,
            candidate_contract,
            context=context,
            merge_conflicts=merge_conflicts,
        )

    def merge_and_evaluate(
        self,
        source_contract: OpenDataContractStandard,
        business_contract: OpenDataContractStandard,
        *,
        effective_date: date | str,
        fail_on_conflict: bool = False,
    ) -> GovernanceAnalysis:
        """Merge and evaluate with the exact same ChangeContext instance."""
        context = self.create_context(effective_date)
        merge_result = self._merge_engine.merge(
            source_contract,
            business_contract,
            context=context,
            fail_on_conflict=fail_on_conflict,
        )
        decision = evaluate_governance_decision(
            business_contract,
            merge_result.contract,
            context=context,
            merge_conflicts=merge_result.conflicts,
        )
        return GovernanceAnalysis(
            context=context,
            merge_result=merge_result,
            decision=decision,
        )
