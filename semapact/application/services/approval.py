"""Application boundary for recording explicit governance review actions."""

from __future__ import annotations

from datetime import datetime

from semapact.approval import ApprovalRecord, build_approval_record
from semapact.contractops import ReviewEvidenceAction
from semapact.governance import GovernanceOperation
from semapact.history import ApprovalHistoryRepository


class ApprovalRecordService:
    """Record and query immutable ApprovalRecord facts without owning approval policy.

    External surfaces such as CLI, CI integrations, SDK callers, or a future UI
    provide an explicit review event. This service normalizes that event through the
    canonical ApprovalRecord builder and persists the resulting artifact through the
    typed history capability.

    The service deliberately does not approve a change, discover provider approvals,
    choose a winning approval, apply quorum rules, or authorize ContractOps actions.
    """

    def __init__(self, approvals: ApprovalHistoryRepository) -> None:
        self._approvals = approvals

    def record_review_action(
        self,
        *,
        decision_id: str,
        change_set_id: str,
        release_plan_id: str,
        version_resolution_id: str,
        operation: GovernanceOperation,
        action: ReviewEvidenceAction,
        actor_reference: str,
        recorded_at: datetime,
        scope_reference: str | None = None,
        capability_reference: str | None = None,
        comment: str | None = None,
        evidence_references: tuple[str, ...] = (),
    ) -> ApprovalRecord:
        """Build and persist one explicit immutable review event idempotently."""
        record = build_approval_record(
            decision_id=decision_id,
            change_set_id=change_set_id,
            release_plan_id=release_plan_id,
            version_resolution_id=version_resolution_id,
            operation=operation,
            action=action,
            actor_reference=actor_reference,
            recorded_at=recorded_at,
            scope_reference=scope_reference,
            capability_reference=capability_reference,
            comment=comment,
            evidence_references=evidence_references,
        )
        self._approvals.put_approval_record(record)
        return record

    def list_review_actions(
        self,
        *,
        decision_id: str,
        change_set_id: str,
        release_plan_id: str,
        version_resolution_id: str,
        operation: GovernanceOperation,
    ) -> tuple[ApprovalRecord, ...]:
        """Return all immutable review events for one exact ContractOps context."""
        return self._approvals.list_approval_records_for_context(
            decision_id=decision_id,
            change_set_id=change_set_id,
            release_plan_id=release_plan_id,
            version_resolution_id=version_resolution_id,
            operation=operation,
        )
