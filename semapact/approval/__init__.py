"""Immutable review-approval artifacts and M2 evidence projection."""

from semapact.approval.builders import build_approval_record
from semapact.approval.evidence import project_review_authorization_evidence
from semapact.approval.integrity import (
    SEMAPACT_APPROVAL_RECORD_NAMESPACE,
    compute_approval_record_id,
    validate_approval_record_identity,
)
from semapact.approval.models import ApprovalRecord

__all__ = [
    "ApprovalRecord",
    "SEMAPACT_APPROVAL_RECORD_NAMESPACE",
    "build_approval_record",
    "compute_approval_record_id",
    "project_review_authorization_evidence",
    "validate_approval_record_identity",
]
