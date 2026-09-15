from __future__ import annotations

from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

from semapact import ApprovalRecord, ApprovalService
from semapact.contractops import ReviewEvidenceAction
from semapact.governance import GovernanceOperation
from semapact.interfaces.commands.approval_cmd import run_approval_record
from semapact.platforms.git import GitWorkingTreeHistoryRepository


def _event() -> dict[str, object]:
    return {
        "decision_id": "decision-1",
        "change_set_id": "change-set-1",
        "release_plan_id": "release-plan-1",
        "version_resolution_id": "version-resolution-1",
        "operation": GovernanceOperation.PUBLISH,
        "action": ReviewEvidenceAction.APPROVE,
        "actor_reference": "github:user:alice",
        "recorded_at": datetime(2026, 9, 16, 1, 0, tzinfo=timezone.utc),
        "capability_reference": "github:team:data-owners",
        "evidence_references": (
            "github:repo:DaorynAI/example:pull:42:review:1001",
        ),
    }


def test_public_approval_service_records_through_typed_history_port(tmp_path: Path) -> None:
    repository = GitWorkingTreeHistoryRepository(tmp_path)
    service = ApprovalService(repository)

    record = service.record_review_action(**_event())

    assert isinstance(record, ApprovalRecord)
    assert repository.get_approval_record(record.approval_id) == record
    assert service.list_review_actions(
        decision_id=record.decision_id,
        change_set_id=record.change_set_id,
        release_plan_id=record.release_plan_id,
        version_resolution_id=record.version_resolution_id,
        operation=record.operation,
    ) == (record,)


def test_cli_adapter_records_external_review_evidence_without_provider_policy(
    tmp_path: Path,
) -> None:
    args = Namespace(
        repository_root=str(tmp_path),
        decision_id="decision-1",
        change_set_id="change-set-1",
        release_plan_id="release-plan-1",
        version_resolution_id="version-resolution-1",
        operation="PUBLISH",
        action="APPROVE",
        actor_reference="github:user:alice",
        recorded_at="2026-09-16T11:00:00+10:00",
        scope_reference=None,
        capability_reference="github:team:data-owners",
        comment="Approved in pull request review",
        evidence_reference=["github:repo:DaorynAI/example:pull:42:review:1001"],
    )

    payload = run_approval_record(args)
    record = GitWorkingTreeHistoryRepository(tmp_path).get_approval_record(
        str(payload["approval_id"])
    )

    assert record.actor_reference == "github:user:alice"
    assert record.recorded_at == datetime(2026, 9, 16, 1, 0, tzinfo=timezone.utc)
    assert record.action is ReviewEvidenceAction.APPROVE
    assert record.evidence_references == (
        "github:repo:DaorynAI/example:pull:42:review:1001",
    )
