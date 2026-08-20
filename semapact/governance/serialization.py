"""Stable, versioned machine-readable GovernanceDecision serialization.

The public JSON contract defined here is deliberately separate from the internal
Pydantic governance models. Internal models may evolve without changing the V1
wire contract consumed by CLI, CI, SDK, MCP, and agent integrations.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from semapact.governance.models import GovernanceDecision, GovernanceReason
from semapact.governance_codes import (
    GovernanceReasonCode,
    GovernanceSeverity,
)
from semapact.lifecycle.changes import (
    GovernanceChange,
    GovernanceChangeDomain,
    GovernanceChangeEvidence,
    GovernanceChangeEvidenceSource,
    GovernanceChangeType,
    GovernanceEntityType,
    governance_change_sort_key,
)

GOVERNANCE_DECISION_SCHEMA_VERSION = "1"
RequiredVersionBumpV1 = Literal["none", "minor", "major"]
DecisionResultV1 = Literal["ALLOW", "BLOCK", "REVIEW"]


class _WireModel(BaseModel):
    """Base model for the public V1 JSON contract."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        populate_by_name=True,
    )


class GovernanceReasonPayloadV1(_WireModel):
    code: GovernanceReasonCode
    severity: GovernanceSeverity
    path: str | None
    message: str


class GovernanceChangeEvidencePayloadV1(_WireModel):
    source: GovernanceChangeEvidenceSource
    code: str


class GovernanceChangePayloadV1(_WireModel):
    change_type: GovernanceChangeType = Field(alias="changeType")
    entity_type: GovernanceEntityType = Field(alias="entityType")
    identity: tuple[str, ...]
    path: str
    field: str | None
    before: JsonValue | None
    after: JsonValue | None
    domain: GovernanceChangeDomain
    breaking: bool
    reason_codes: tuple[GovernanceReasonCode, ...] = Field(alias="reasonCodes")
    evidence: tuple[GovernanceChangeEvidencePayloadV1, ...]


class ValidationPayloadV1(_WireModel):
    valid: bool
    issue_codes: tuple[GovernanceReasonCode, ...] = Field(alias="issueCodes")
    issues: tuple[GovernanceReasonPayloadV1, ...]


class PolicyPayloadV1(_WireModel):
    valid: bool
    id_violation: bool = Field(alias="idViolation")
    version_violation: bool = Field(alias="versionViolation")
    retired_violation: bool = Field(alias="retiredViolation")


class DecisionEvidencePayloadV1(_WireModel):
    has_changes: bool = Field(alias="hasChanges")
    merge_conflicts_count: int = Field(alias="mergeConflictsCount", ge=0)


class GovernanceDecisionPayloadV1(_WireModel):
    """Stable public GovernanceDecision JSON schema, version 1."""

    schema_version: Literal["1"] = Field(alias="schemaVersion")
    decision_id: str = Field(alias="decisionId")
    decision: DecisionResultV1
    contract_id: str = Field(alias="contractId")
    effective_date: str = Field(alias="effectiveDate")
    breaking: bool
    required_version_bump: RequiredVersionBumpV1 = Field(alias="requiredVersionBump")
    reason_codes: tuple[GovernanceReasonCode, ...] = Field(alias="reasonCodes")
    reasons: tuple[GovernanceReasonPayloadV1, ...]
    changes: tuple[GovernanceChangePayloadV1, ...]
    validation: ValidationPayloadV1
    policy: PolicyPayloadV1
    evidence: DecisionEvidencePayloadV1


def _reason_sort_key(reason: GovernanceReason) -> tuple[str, str, str, str]:
    return (
        reason.code.value,
        reason.path or "",
        reason.severity.value,
        reason.message,
    )


def _reason_to_payload(reason: GovernanceReason) -> GovernanceReasonPayloadV1:
    return GovernanceReasonPayloadV1(
        code=reason.code,
        severity=reason.severity,
        path=reason.path,
        message=reason.message,
    )


def _change_evidence_to_payload(
    evidence: GovernanceChangeEvidence,
) -> GovernanceChangeEvidencePayloadV1:
    return GovernanceChangeEvidencePayloadV1(
        source=evidence.source,
        code=evidence.code,
    )


def _canonicalize_json_value(value: JsonValue | None) -> JsonValue | None:
    """Recursively normalize JSON objects to deterministic key ordering."""

    if isinstance(value, Mapping):
        return {
            str(key): _canonicalize_json_value(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, list):
        return [_canonicalize_json_value(item) for item in value]
    return value


def _change_to_payload(change: GovernanceChange) -> GovernanceChangePayloadV1:
    evidence = tuple(
        _change_evidence_to_payload(item)
        for item in sorted(
            change.evidence,
            key=lambda item: (item.source.value, item.code),
        )
    )
    reason_codes = tuple(sorted(change.reason_codes, key=lambda code: code.value))
    return GovernanceChangePayloadV1(
        change_type=change.change_type,
        entity_type=change.entity_type,
        identity=change.identity,
        path=change.path,
        field=change.field,
        before=_canonicalize_json_value(change.before),
        after=_canonicalize_json_value(change.after),
        domain=change.domain,
        breaking=change.breaking,
        reason_codes=reason_codes,
        evidence=evidence,
    )


def governance_decision_to_payload(
    decision: GovernanceDecision,
) -> GovernanceDecisionPayloadV1:
    """Map an internal GovernanceDecision to the stable V1 public wire model."""

    if not isinstance(decision, GovernanceDecision):
        raise TypeError(
            "governance_decision_to_payload requires GovernanceDecision, "
            f"got {type(decision).__name__}"
        )

    reasons = tuple(
        _reason_to_payload(reason)
        for reason in sorted(decision.reasons, key=_reason_sort_key)
    )
    validation_issues = tuple(
        _reason_to_payload(reason)
        for reason in sorted(decision.validation.issues, key=_reason_sort_key)
    )
    changes = tuple(
        _change_to_payload(change)
        for change in sorted(decision.changes, key=governance_change_sort_key)
    )

    return GovernanceDecisionPayloadV1(
        schema_version=GOVERNANCE_DECISION_SCHEMA_VERSION,
        decision_id=decision.decision_id,
        decision=decision.decision.value,
        contract_id=decision.contract_id,
        effective_date=decision.context.effective_date.isoformat(),
        breaking=decision.breaking,
        required_version_bump=decision.required_version_bump,
        reason_codes=tuple(sorted({reason.code for reason in decision.reasons}, key=lambda code: code.value)),
        reasons=reasons,
        changes=changes,
        validation=ValidationPayloadV1(
            valid=decision.validation.valid,
            issue_codes=tuple(
                sorted(
                    {issue.code for issue in decision.validation.issues},
                    key=lambda code: code.value,
                )
            ),
            issues=validation_issues,
        ),
        policy=PolicyPayloadV1(
            valid=decision.policy.valid,
            id_violation=decision.policy.id_violation,
            version_violation=decision.policy.version_violation,
            retired_violation=decision.policy.retired_violation,
        ),
        evidence=DecisionEvidencePayloadV1(
            has_changes=decision.evidence.has_changes,
            merge_conflicts_count=decision.evidence.merge_conflicts_count,
        ),
    )


def governance_decision_to_dict(decision: GovernanceDecision) -> dict[str, Any]:
    """Return the stable V1 public JSON object with documented camelCase keys."""

    return governance_decision_to_payload(decision).model_dump(
        mode="json",
        by_alias=True,
    )


def governance_decision_payload_to_json(
    payload: GovernanceDecisionPayloadV1,
) -> str:
    """Serialize a validated V1 payload to canonical byte-equivalent JSON text."""

    data = payload.model_dump(mode="json", by_alias=True)
    return json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
    ) + "\n"


def governance_decision_to_json(decision: GovernanceDecision) -> str:
    """Serialize an internal decision to canonical V1 JSON text."""

    return governance_decision_payload_to_json(
        governance_decision_to_payload(decision)
    )


def parse_governance_decision_json(
    payload: str | bytes,
) -> GovernanceDecisionPayloadV1:
    """Parse and validate public GovernanceDecision V1 JSON without rebuilding internals."""

    return GovernanceDecisionPayloadV1.model_validate_json(payload)


def governance_decision_json_schema() -> dict[str, Any]:
    """Return the public GovernanceDecision V1 JSON Schema using wire aliases."""

    return GovernanceDecisionPayloadV1.model_json_schema(by_alias=True)


__all__ = [
    "GOVERNANCE_DECISION_SCHEMA_VERSION",
    "DecisionEvidencePayloadV1",
    "GovernanceChangeEvidencePayloadV1",
    "GovernanceChangePayloadV1",
    "GovernanceDecisionPayloadV1",
    "GovernanceReasonPayloadV1",
    "PolicyPayloadV1",
    "ValidationPayloadV1",
    "governance_decision_json_schema",
    "governance_decision_payload_to_json",
    "governance_decision_to_dict",
    "governance_decision_to_json",
    "governance_decision_to_payload",
    "parse_governance_decision_json",
]
