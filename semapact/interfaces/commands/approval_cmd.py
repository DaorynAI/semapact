"""CLI adapters for explicit governance approval recording."""

from __future__ import annotations

from argparse import Namespace
from semapact.application.services.approval_record import ApprovalRecordService
from semapact.contractops import ReviewEvidenceAction
from semapact.governance import GovernanceOperation
from semapact.interfaces.parsing import parse_iso_timestamp
from semapact.platforms.git import GitWorkingTreeHistoryRepository


def run_approval_record(args: Namespace) -> dict[str, object]:
    """Record one explicit review event through the application service boundary."""
    recorded_at = parse_iso_timestamp(args.recorded_at)
    service = ApprovalRecordService(
        GitWorkingTreeHistoryRepository(args.repository_root),
    )
    record = service.record_review_action(
        decision_id=args.decision_id,
        change_set_id=args.change_set_id,
        release_plan_id=args.release_plan_id,
        version_resolution_id=args.version_resolution_id,
        operation=GovernanceOperation(args.operation),
        action=ReviewEvidenceAction(args.action),
        actor_reference=args.actor_reference,
        recorded_at=recorded_at,
        scope_reference=args.scope_reference,
        capability_reference=args.capability_reference,
        comment=args.comment,
        evidence_references=tuple(args.evidence_reference or ()),
    )
    return record.model_dump(mode="json", by_alias=True)


