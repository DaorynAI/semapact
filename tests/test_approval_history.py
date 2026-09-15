from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from semapact.approval import (
    build_approval_record,
    project_review_authorization_evidence,
    validate_approval_record_identity,
)
from semapact.contractops import ReviewEvidenceAction
from semapact.governance import GovernanceOperation
from semapact.history import ApprovalHistoryRepository, HistoryCorruptionError
from semapact.platforms.git import GitWorkingTreeHistoryRepository


CONTEXT = {
    "decision_id": "decision-1",
    "change_set_id": "change-set-1",
    "release_plan_id": "release-plan-1",
    "version_resolution_id": "version-resolution-1",
    "operation": GovernanceOperation.PUBLISH,
}


def _approval(
    *,
    actor_reference: str = "user:alice",
    action: ReviewEvidenceAction = ReviewEvidenceAction.APPROVE,
    recorded_at: datetime = datetime(2026, 9, 16, 1, 0, tzinfo=timezone.utc),
    scope_reference: str | None = None,
    comment: str | None = "reviewed",
    evidence_references: tuple[str, ...] = ("ticket:2", "ticket:1"),
):
    return build_approval_record(
        **CONTEXT,
        actor_reference=actor_reference,
        action=action,
        recorded_at=recorded_at,
        scope_reference=scope_reference,
        capability_reference="role:data-governance-reviewer",
        comment=comment,
        evidence_references=evidence_references,
    )


def test_approval_builder_normalizes_event_before_identity() -> None:
    brisbane = timezone(timedelta(hours=10))
    first = _approval(
        recorded_at=datetime(2026, 9, 16, 11, 0, tzinfo=brisbane),
        evidence_references=("ticket:2", "ticket:1", "ticket:2"),
    )
    second = _approval(
        recorded_at=datetime(2026, 9, 16, 1, 0, tzinfo=timezone.utc),
        evidence_references=("ticket:1", "ticket:2"),
    )

    assert first == second
    assert first.recorded_at == datetime(2026, 9, 16, 1, 0, tzinfo=timezone.utc)
    assert first.evidence_references == ("ticket:1", "ticket:2")
    validate_approval_record_identity(first)


def test_distinct_review_events_have_distinct_identity() -> None:
    first = _approval()
    later = _approval(
        recorded_at=datetime(2026, 9, 16, 1, 1, tzinfo=timezone.utc),
    )
    other_actor = _approval(actor_reference="user:bob")
    rejected = _approval(action=ReviewEvidenceAction.REJECT)

    assert len(
        {
            first.approval_id,
            later.approval_id,
            other_actor.approval_id,
            rejected.approval_id,
        }
    ) == 4


def test_approval_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        _approval(recorded_at=datetime(2026, 9, 16, 1, 0))


def test_tampered_approval_identity_fails_closed() -> None:
    record = _approval()
    tampered = record.model_copy(update={"comment": "changed after identity"})

    with pytest.raises(ValueError, match="deterministic approval identity"):
        validate_approval_record_identity(tampered)


def test_projection_is_lossless_for_m2_authorization_scope() -> None:
    record = _approval(scope_reference="deployment-plan:abc")

    evidence = project_review_authorization_evidence(record)

    assert evidence.evidence_reference == record.approval_id
    assert evidence.decision_id == record.decision_id
    assert evidence.change_set_id == record.change_set_id
    assert evidence.release_plan_id == record.release_plan_id
    assert evidence.version_resolution_id == record.version_resolution_id
    assert evidence.operation is record.operation
    assert evidence.action is record.action
    assert evidence.scope_reference == record.scope_reference


def test_approval_records_round_trip_through_typed_history_port(tmp_path: Path) -> None:
    backend = GitWorkingTreeHistoryRepository(tmp_path)
    approvals: ApprovalHistoryRepository = backend
    record = _approval()

    approvals.put_approval_record(record)
    approvals.put_approval_record(record)

    assert approvals.get_approval_record(record.approval_id) == record
    assert backend.inspect_history_integrity() == ()


def test_invalid_content_cannot_reuse_existing_approval_identity(tmp_path: Path) -> None:
    repository = GitWorkingTreeHistoryRepository(tmp_path)
    record = _approval()
    repository.put_approval_record(record)
    tampered = record.model_copy(update={"comment": "different content"})

    with pytest.raises(HistoryCorruptionError, match="is invalid"):
        repository.put_approval_record(tampered)


def test_exact_context_listing_preserves_all_actions_deterministically(
    tmp_path: Path,
) -> None:
    repository = GitWorkingTreeHistoryRepository(tmp_path)
    matching = (
        _approval(actor_reference="user:alice"),
        _approval(actor_reference="user:bob"),
        _approval(
            actor_reference="user:carol",
            action=ReviewEvidenceAction.REQUEST_CHANGES,
        ),
    )
    wrong_operation = build_approval_record(
        **{**CONTEXT, "operation": GovernanceOperation.APPLY},
        actor_reference="user:dana",
        action=ReviewEvidenceAction.APPROVE,
        recorded_at=datetime(2026, 9, 16, 1, 2, tzinfo=timezone.utc),
    )
    wrong_decision = build_approval_record(
        **{**CONTEXT, "decision_id": "decision-2"},
        actor_reference="user:erin",
        action=ReviewEvidenceAction.APPROVE,
        recorded_at=datetime(2026, 9, 16, 1, 3, tzinfo=timezone.utc),
    )

    for record in reversed((*matching, wrong_operation, wrong_decision)):
        repository.put_approval_record(record)

    listed = repository.list_approval_records_for_context(**CONTEXT)

    assert {item.approval_id for item in listed} == {
        item.approval_id for item in matching
    }
    assert [item.approval_id for item in listed] == sorted(
        item.approval_id for item in matching
    )
    assert {item.action for item in listed} == {
        ReviewEvidenceAction.APPROVE,
        ReviewEvidenceAction.REQUEST_CHANGES,
    }
