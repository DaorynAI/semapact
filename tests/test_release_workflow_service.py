from __future__ import annotations

from datetime import datetime, timezone

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)
from pydantic import ValidationError as PydanticValidationError

from semapact.application.models.release import ReleaseBundle
from semapact.application.services.contract_release_history import (
    ContractReleaseHistoryService,
)
from semapact.application.services.release_approval import ReleaseApprovalResolver
from semapact.application.services.release_workflow import ReleaseWorkflowService
from semapact.exceptions import ContractOpsAuthorizationError
from semapact.governance import DecisionResult, GovernanceOperation
from semapact.platforms.git import GitWorkingTreeHistoryRepository


def _contract(*, include_created_at: bool = False) -> OpenDataContractStandard:
    properties = [
        SchemaProperty(
            name="id",
            logicalType="string",
            physicalType="varchar(255)",
            required=True,
        )
    ]
    if include_created_at:
        properties.append(
            SchemaProperty(
                name="created_at",
                logicalType="timestamp",
                physicalType="timestamp",
                required=False,
            )
        )
    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="orders-product",
        name="Orders",
        version="1.2.3",
        status="active",
        schema=[SchemaObject(name="orders", properties=properties)],
    )


def _bundle() -> ReleaseBundle:
    return ReleaseWorkflowService().assess(
        _contract(),
        _contract(include_created_at=True),
        effective_date="2026-09-20",
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
    )


def test_release_assess_is_target_neutral_and_resolves_version_once() -> None:
    bundle = _bundle()

    assert bundle.decision.decision is DecisionResult.REVIEW
    assert bundle.version_resolution.current_version == "1.2.3"
    assert bundle.version_resolution.selected_version == "1.3.0"
    assert bundle.release_snapshot.selected_version == "1.3.0"
    assert "target" not in bundle.model_dump(mode="json")


def test_release_bundle_digest_is_deterministic_and_tamper_evident() -> None:
    first = _bundle()
    second = _bundle()
    assert first == second
    assert first.bundle_digest == second.bundle_digest

    payload = first.model_dump(mode="json")
    payload["bundle_digest"] = "sha256:" + ("0" * 64)
    with pytest.raises(PydanticValidationError, match="digest does not match"):
        ReleaseBundle.model_validate(payload)


def test_release_approval_binds_publish_scope_and_exact_bundle() -> None:
    bundle = _bundle()
    approval = ReleaseWorkflowService().approve(
        bundle,
        actor_reference="github:user:reviewer",
        recorded_at=datetime(2026, 9, 20, 2, tzinfo=timezone.utc),
    )

    assert approval.operation is GovernanceOperation.PUBLISH
    assert approval.scope_reference == bundle.release_snapshot.release_snapshot_id
    assert approval.evidence_references == (bundle.bundle_digest,)


def test_review_release_finalize_requires_exact_approval(tmp_path) -> None:
    bundle = _bundle()
    repository = GitWorkingTreeHistoryRepository(tmp_path)
    workflow = ReleaseWorkflowService()

    with pytest.raises(ContractOpsAuthorizationError, match="requires approval"):
        workflow.finalize(
            bundle,
            release_history=ContractReleaseHistoryService(repository),
        )

    approval = workflow.approve(
        bundle,
        actor_reference="github:user:reviewer",
        recorded_at=datetime(2026, 9, 20, 2, tzinfo=timezone.utc),
    )
    repository.put_approval_record(approval)
    record = workflow.finalize(
        bundle,
        release_history=ContractReleaseHistoryService(repository),
        approval=approval,
    )

    assert record.contract_version == "1.3.0"
    assert record.release_snapshot_id == bundle.release_snapshot.release_snapshot_id
    assert record.source_revision_ref == "git:candidate"
    assert (
        repository.get_contract_release(record.contract_release_id)
        == record
    )


def test_release_approval_resolver_finds_only_exact_bundle(tmp_path) -> None:
    bundle = _bundle()
    repository = GitWorkingTreeHistoryRepository(tmp_path)
    approval = ReleaseWorkflowService().approve(
        bundle,
        actor_reference="github:user:reviewer",
        recorded_at=datetime(2026, 9, 20, 2, tzinfo=timezone.utc),
    )
    repository.put_approval_record(approval)

    assert ReleaseApprovalResolver(repository).resolve(bundle) == approval

    tampered = bundle.model_copy(
        update={"bundle_digest": "sha256:" + ("f" * 64)}
    )
    assert ReleaseApprovalResolver(repository).resolve(tampered) is None
