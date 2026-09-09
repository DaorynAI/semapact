from __future__ import annotations

from datetime import date

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.change_context import ChangeContext
from semapact.contractops import (
    ReviewAuthorizationEvidence,
    ReviewEvidenceAction,
    VersionAuthorityConfig,
    apply_contract_release,
    authorize_contract_operation,
    build_change_set_from_decision,
    build_release_plan,
    publish_contract_release,
    resolve_release_version,
)
from semapact.exceptions import ContractOpsAuthorizationError, ReleaseValidationError
from semapact.governance import DecisionResult, evaluate_governance_decision
from semapact.governance.gate import GovernanceOperation


CONTEXT = ChangeContext(effective_date=date(2026, 9, 9))


def _contract(
    *,
    contract_id: str = "orders-product",
    contract_name: str = "orders",
    version: str = "1.0.0",
    include_created_at: bool = False,
) -> OpenDataContractStandard:
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
        id=contract_id,
        name=contract_name,
        version=version,
        status="active",
        schema=[SchemaObject(name="orders", properties=properties)],
    )


def _release_context(kind: str):
    base = _contract(contract_name="orders-old")
    if kind == "allow":
        candidate = _contract(contract_name="orders-new")
    elif kind == "review":
        candidate = _contract(contract_name="orders-old", include_created_at=True)
    else:  # pragma: no cover - test helper guard
        raise ValueError(kind)

    decision = evaluate_governance_decision(base, candidate, context=CONTEXT)
    change_set = build_change_set_from_decision(
        decision,
        base_revision_ref="rev:base",
        candidate_revision_ref="rev:candidate",
        source="test",
        actor_reference="actor:test",
    )
    release_plan = build_release_plan(change_set, decision)
    version_resolution = resolve_release_version(
        release_plan,
        current_version="1.0.0",
        config=VersionAuthorityConfig(),
    )
    return candidate, decision, change_set, release_plan, version_resolution


def _review_evidence(
    decision,
    change_set,
    release_plan,
    version_resolution,
    operation: GovernanceOperation,
) -> ReviewAuthorizationEvidence:
    return ReviewAuthorizationEvidence(
        evidence_reference=f"approval:{operation.value.lower()}",
        decision_id=decision.decision_id,
        change_set_id=change_set.change_set_id,
        release_plan_id=release_plan.release_plan_id,
        version_resolution_id=version_resolution.version_resolution_id,
        operation=operation,
        action=ReviewEvidenceAction.APPROVE,
    )


def _authorization(
    decision,
    change_set,
    release_plan,
    version_resolution,
    operation: GovernanceOperation,
    *,
    approve_review: bool = True,
):
    evidence = None
    if decision.decision is DecisionResult.REVIEW and approve_review:
        evidence = _review_evidence(
            decision,
            change_set,
            release_plan,
            version_resolution,
            operation,
        )
    return authorize_contract_operation(
        decision,
        change_set,
        release_plan,
        version_resolution,
        operation,
        evidence=evidence,
    )


class RecordingPublisher:
    def __init__(self) -> None:
        self.calls = []

    def publish(self, release) -> str:
        self.calls.append(release)
        return f"published:{release.applied_release_id}"


def test_apply_metadata_only_release_uses_selected_patch_without_mutating_candidate() -> None:
    candidate, decision, change_set, release_plan, version_resolution = _release_context(
        "allow"
    )
    authorization = _authorization(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.APPLY,
    )

    assert decision.decision is DecisionResult.ALLOW
    assert release_plan.required_version_bump == "none"
    assert version_resolution.selected_version == "1.0.1"

    first = apply_contract_release(
        candidate,
        candidate_revision_ref="rev:candidate",
        decision=decision,
        change_set=change_set,
        release_plan=release_plan,
        version_resolution=version_resolution,
        authorization=authorization,
    )
    second = apply_contract_release(
        candidate,
        candidate_revision_ref="rev:candidate",
        decision=decision,
        change_set=change_set,
        release_plan=release_plan,
        version_resolution=version_resolution,
        authorization=authorization,
    )

    assert first == second
    assert first.applied_release_id == second.applied_release_id
    assert first.selected_version == "1.0.1"
    assert first.release_revision_ref == "rev:candidate"
    assert first.to_contract().version == "1.0.1"
    assert first.to_contract().name == "orders-new"
    assert candidate.version == "1.0.0"


def test_authorized_review_can_apply_without_rewriting_decision() -> None:
    candidate, decision, change_set, release_plan, version_resolution = _release_context(
        "review"
    )
    authorization = _authorization(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.APPLY,
    )

    release = apply_contract_release(
        candidate,
        candidate_revision_ref="rev:candidate",
        decision=decision,
        change_set=change_set,
        release_plan=release_plan,
        version_resolution=version_resolution,
        authorization=authorization,
    )

    assert decision.decision is DecisionResult.REVIEW
    assert authorization.allowed is True
    assert release.selected_version == "1.1.0"
    assert release.to_contract().version == "1.1.0"
    assert len(release.to_contract().schema_[0].properties) == 2


def test_review_without_approval_cannot_apply() -> None:
    candidate, decision, change_set, release_plan, version_resolution = _release_context(
        "review"
    )
    authorization = _authorization(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.APPLY,
        approve_review=False,
    )

    assert authorization.allowed is False
    with pytest.raises(ContractOpsAuthorizationError, match="not authorized"):
        apply_contract_release(
            candidate,
            candidate_revision_ref="rev:candidate",
            decision=decision,
            change_set=change_set,
            release_plan=release_plan,
            version_resolution=version_resolution,
            authorization=authorization,
        )


def test_apply_fails_closed_for_stale_candidate_revision() -> None:
    candidate, decision, change_set, release_plan, version_resolution = _release_context(
        "allow"
    )
    authorization = _authorization(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.APPLY,
    )

    with pytest.raises(ReleaseValidationError, match="planned release revision"):
        apply_contract_release(
            candidate,
            candidate_revision_ref="rev:stale",
            decision=decision,
            change_set=change_set,
            release_plan=release_plan,
            version_resolution=version_resolution,
            authorization=authorization,
        )


def test_apply_fails_closed_when_candidate_version_drifted() -> None:
    candidate, decision, change_set, release_plan, version_resolution = _release_context(
        "allow"
    )
    authorization = _authorization(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.APPLY,
    )
    drifted_candidate = candidate.model_copy(deep=True)
    drifted_candidate.version = "9.0.0"

    with pytest.raises(ReleaseValidationError, match="current_version"):
        apply_contract_release(
            drifted_candidate,
            candidate_revision_ref="rev:candidate",
            decision=decision,
            change_set=change_set,
            release_plan=release_plan,
            version_resolution=version_resolution,
            authorization=authorization,
        )


def test_apply_authorization_cannot_authorize_publish() -> None:
    candidate, decision, change_set, release_plan, version_resolution = _release_context(
        "allow"
    )
    apply_authorization = _authorization(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.APPLY,
    )
    release = apply_contract_release(
        candidate,
        candidate_revision_ref="rev:candidate",
        decision=decision,
        change_set=change_set,
        release_plan=release_plan,
        version_resolution=version_resolution,
        authorization=apply_authorization,
    )
    publisher = RecordingPublisher()

    with pytest.raises(ReleaseValidationError, match="PUBLISH authorization"):
        publish_contract_release(
            release,
            authorization=apply_authorization,
            publisher=publisher,
        )

    assert publisher.calls == []


def test_publish_invokes_adapter_only_after_exact_publish_authorization() -> None:
    candidate, decision, change_set, release_plan, version_resolution = _release_context(
        "allow"
    )
    apply_authorization = _authorization(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.APPLY,
    )
    publish_authorization = _authorization(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.PUBLISH,
    )
    release = apply_contract_release(
        candidate,
        candidate_revision_ref="rev:candidate",
        decision=decision,
        change_set=change_set,
        release_plan=release_plan,
        version_resolution=version_resolution,
        authorization=apply_authorization,
    )
    publisher = RecordingPublisher()

    first = publish_contract_release(
        release,
        authorization=publish_authorization,
        publisher=publisher,
    )
    second = publish_contract_release(
        release,
        authorization=publish_authorization,
        publisher=RecordingPublisher(),
    )

    assert len(publisher.calls) == 1
    assert publisher.calls[0] == release
    assert first == second
    assert first.publication_id == second.publication_id
    assert first.applied_release_id == release.applied_release_id
    assert first.authorization_id == publish_authorization.authorization_id
    assert first.publication_reference == f"published:{release.applied_release_id}"


def test_review_without_publish_approval_never_invokes_publisher() -> None:
    candidate, decision, change_set, release_plan, version_resolution = _release_context(
        "review"
    )
    apply_authorization = _authorization(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.APPLY,
    )
    denied_publish_authorization = _authorization(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.PUBLISH,
        approve_review=False,
    )
    release = apply_contract_release(
        candidate,
        candidate_revision_ref="rev:candidate",
        decision=decision,
        change_set=change_set,
        release_plan=release_plan,
        version_resolution=version_resolution,
        authorization=apply_authorization,
    )
    publisher = RecordingPublisher()

    with pytest.raises(ContractOpsAuthorizationError, match="not authorized"):
        publish_contract_release(
            release,
            authorization=denied_publish_authorization,
            publisher=publisher,
        )

    assert publisher.calls == []
