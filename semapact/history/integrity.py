"""Deterministic identity for history-owned audit records."""

from __future__ import annotations

import uuid

from semapact.history.models import ReleaseRecord
from semapact.utils.deterministic import deterministic_uuid5


SEMAPACT_RELEASE_RECORD_NAMESPACE = uuid.UUID(
    "9f750d1c-8f0a-491a-b861-8e349fc351cb"
)


def compute_release_record_id(
    *,
    contract_id: str,
    contract_version: str,
    decision_id: str,
    change_set_id: str,
    release_plan_id: str,
    version_resolution_id: str,
    authorization_id: str,
    applied_release_id: str,
    released_revision_id: str,
    required_version_bump: str,
    actual_version_bump: str,
    version_authority: str,
    authority_reference: str | None,
    review_evidence_reference: str | None,
    review_evidence_action: str | None,
) -> str:
    """Derive one stable identity from the complete immutable release audit record."""
    return deterministic_uuid5(
        SEMAPACT_RELEASE_RECORD_NAMESPACE,
        {
            "contract_id": contract_id,
            "contract_version": contract_version,
            "decision_id": decision_id,
            "change_set_id": change_set_id,
            "release_plan_id": release_plan_id,
            "version_resolution_id": version_resolution_id,
            "authorization_id": authorization_id,
            "applied_release_id": applied_release_id,
            "released_revision_id": released_revision_id,
            "required_version_bump": required_version_bump,
            "actual_version_bump": actual_version_bump,
            "version_authority": version_authority,
            "authority_reference": authority_reference,
            "review_evidence_reference": review_evidence_reference,
            "review_evidence_action": review_evidence_action,
        },
    )


def validate_release_record_identity(record: ReleaseRecord) -> None:
    """Fail closed when a persisted release record ID does not match its content."""
    expected = compute_release_record_id(
        contract_id=record.contract_id,
        contract_version=record.contract_version,
        decision_id=record.decision_id,
        change_set_id=record.change_set_id,
        release_plan_id=record.release_plan_id,
        version_resolution_id=record.version_resolution_id,
        authorization_id=record.authorization_id,
        applied_release_id=record.applied_release_id,
        released_revision_id=record.released_revision_id,
        required_version_bump=record.required_version_bump,
        actual_version_bump=record.actual_version_bump,
        version_authority=record.version_authority.value,
        authority_reference=record.authority_reference,
        review_evidence_reference=record.review_evidence_reference,
        review_evidence_action=(
            record.review_evidence_action.value
            if record.review_evidence_action is not None
            else None
        ),
    )
    if record.release_record_id != expected:
        raise ValueError("ReleaseRecord deterministic identity does not match its content")
