"""Stable, versioned public contract for SemaPact governance decisions (v1)."""

from __future__ import annotations

import json
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from semapact.governance.models import (
    DecisionResult,
    GovernanceDecision,
    GovernanceReason,
)
from semapact.governance_codes import GovernanceReasonCode, GovernanceSeverity
from semapact.lifecycle.changes import (
    GovernanceChange,
    GovernanceChangeDomain,
    GovernanceChangeEvidence,
    GovernanceChangeEvidenceSource,
    GovernanceChangeType,
    GovernanceEntityType,
)


class PublicGovernanceModel(BaseModel):
    """Shared base model for all public governance models.

    Enforces immutability (frozen=True), forbids unknown fields (extra="forbid"),
    and allows populating by python attribute name or JSON alias (populate_by_name=True).
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        populate_by_name=True,
    )


class PublicChangeContextV1(PublicGovernanceModel):
    """Public representation of contextual evaluation parameters."""

    effective_date: str = Field(alias="effectiveDate")


class PublicGovernanceReasonV1(PublicGovernanceModel):
    """Public structured reason for a governance outcome or violation."""

    code: str
    severity: str
    message: str
    path: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class PublicValidationOutcomeV1(PublicGovernanceModel):
    """Public schema and quality validation outcome."""

    valid: bool
    issues: tuple[PublicGovernanceReasonV1, ...] = ()


class PublicPolicyOutcomeV1(PublicGovernanceModel):
    """Public lifecycle policy outcome."""

    valid: bool
    id_violation: bool = Field(default=False, alias="idViolation")
    version_violation: bool = Field(default=False, alias="versionViolation")
    retired_violation: bool = Field(default=False, alias="retiredViolation")
    violations: tuple[PublicGovernanceReasonV1, ...] = ()


class PublicChangeEvidenceV1(PublicGovernanceModel):
    """Public summarized evidence for contract mutations."""

    has_changes: bool = Field(default=False, alias="hasChanges")
    merge_conflicts_count: int = Field(default=0, alias="mergeConflictsCount")


class PublicGovernanceChangeEvidenceV1(PublicGovernanceModel):
    """Public evidence source supporting a semantic change."""

    source: str
    description: str


class PublicGovernanceChangeV1(PublicGovernanceModel):
    """Public canonical representation of a single semantic contract change."""

    change_type: str = Field(alias="changeType")
    entity_type: str = Field(alias="entityType")
    identity: tuple[str, ...]
    path: str
    field: str | None = None
    before: JsonValue | None = None
    after: JsonValue | None = None
    domain: str
    breaking: bool = False
    reason_codes: tuple[str, ...] = Field(default=(), alias="reasonCodes")
    evidence: tuple[PublicGovernanceChangeEvidenceV1, ...] = ()


class PublicGovernanceDecisionV1(PublicGovernanceModel):
    """Authoritative, versioned public contract for a SemaPact governance decision."""

    schema_version: Literal["1"] = Field(default="1", alias="schemaVersion")
    decision_id: str = Field(alias="decisionId")
    decision: str
    contract_id: str = Field(alias="contractId")
    context: PublicChangeContextV1
    breaking: bool
    required_version_bump: str = Field(alias="requiredVersionBump")
    reason_codes: tuple[str, ...] = Field(default=(), alias="reasonCodes")
    reasons: tuple[PublicGovernanceReasonV1, ...] = ()
    validation: PublicValidationOutcomeV1
    policy: PublicPolicyOutcomeV1
    evidence: PublicChangeEvidenceV1
    changes: tuple[PublicGovernanceChangeV1, ...] = ()

    @classmethod
    def from_domain(cls, decision: GovernanceDecision) -> PublicGovernanceDecisionV1:
        """Construct PublicGovernanceDecisionV1 from an internal GovernanceDecision domain model."""
        return to_public_governance_decision(decision)

    def to_canonical_json(self, *, indent: int | None = None) -> str:
        """Serialize to deterministic canonical JSON."""
        return serialize_public_governance_decision(self, indent=indent)

    def to_canonical_dict(self) -> dict[str, Any]:
        """Convert to JSON-compatible dictionary with external camelCase field names."""
        return self.model_dump(mode="json", by_alias=True)


def _project_reason(reason: GovernanceReason) -> PublicGovernanceReasonV1:
    """Project internal GovernanceReason to PublicGovernanceReasonV1."""
    code_val = reason.code.value if isinstance(reason.code, GovernanceReasonCode) else str(reason.code)
    severity_val = (
        reason.severity.value
        if isinstance(reason.severity, GovernanceSeverity)
        else str(reason.severity)
    )
    details_copy = {k: v for k, v in sorted(reason.details.items())} if reason.details else {}
    return PublicGovernanceReasonV1(
        code=code_val,
        severity=severity_val,
        message=reason.message,
        path=reason.path,
        details=details_copy,
    )


def _project_change_evidence(evidence: GovernanceChangeEvidence) -> PublicGovernanceChangeEvidenceV1:
    """Project internal GovernanceChangeEvidence to PublicGovernanceChangeEvidenceV1."""
    source_val = (
        evidence.source.value
        if isinstance(evidence.source, GovernanceChangeEvidenceSource)
        else str(evidence.source)
    )
    return PublicGovernanceChangeEvidenceV1(
        source=source_val,
        description=evidence.description,
    )


def _project_change(change: GovernanceChange) -> PublicGovernanceChangeV1:
    """Project internal GovernanceChange to PublicGovernanceChangeV1."""
    change_type_val = (
        change.change_type.value
        if isinstance(change.change_type, GovernanceChangeType)
        else str(change.change_type)
    )
    entity_type_val = (
        change.entity_type.value
        if isinstance(change.entity_type, GovernanceEntityType)
        else str(change.entity_type)
    )
    domain_val = (
        change.domain.value
        if isinstance(change.domain, GovernanceChangeDomain)
        else str(change.domain)
    )
    projected_evidence = tuple(_project_change_evidence(ev) for ev in change.evidence)
    reason_codes_val = tuple(
        rc.value if isinstance(rc, GovernanceReasonCode) else str(rc)
        for rc in change.reason_codes
    )
    return PublicGovernanceChangeV1(
        change_type=change_type_val,
        entity_type=entity_type_val,
        identity=tuple(change.identity),
        path=change.path,
        field=change.field,
        before=change.before,
        after=change.after,
        domain=domain_val,
        breaking=change.breaking,
        reason_codes=reason_codes_val,
        evidence=projected_evidence,
    )


def to_public_governance_decision(decision: GovernanceDecision) -> PublicGovernanceDecisionV1:
    """Project an internal GovernanceDecision domain model into a PublicGovernanceDecisionV1."""
    if not isinstance(decision, GovernanceDecision):
        raise TypeError(
            f"to_public_governance_decision requires GovernanceDecision, got {type(decision).__name__}"
        )

    # 1. Project context
    context = PublicChangeContextV1(
        effective_date=decision.context.effective_date.isoformat()
    )

    # 2. Project reasons
    projected_reasons = tuple(_project_reason(r) for r in decision.reasons)

    # 3. Project validation outcome
    validation_issues = tuple(_project_reason(r) for r in decision.validation.issues)
    validation = PublicValidationOutcomeV1(
        valid=decision.validation.valid,
        issues=validation_issues,
    )

    # 4. Project policy outcome (omits internal BreakingChange structs)
    policy_violations = tuple(_project_reason(r) for r in decision.policy.violations)
    policy = PublicPolicyOutcomeV1(
        valid=decision.policy.valid,
        id_violation=decision.policy.id_violation,
        version_violation=decision.policy.version_violation,
        retired_violation=decision.policy.retired_violation,
        violations=policy_violations,
    )

    # 5. Project evidence
    evidence = PublicChangeEvidenceV1(
        has_changes=decision.evidence.has_changes,
        merge_conflicts_count=decision.evidence.merge_conflicts_count,
    )

    # 6. Project canonical changes
    projected_changes = tuple(_project_change(c) for c in decision.changes)

    # 7. Aggregate stable unique reason codes in deterministic order
    ordered_reason_codes: list[str] = []
    seen_codes: set[str] = set()

    for r in projected_reasons:
        if r.code not in seen_codes:
            seen_codes.add(r.code)
            ordered_reason_codes.append(r.code)

    for c in projected_changes:
        for rc in c.reason_codes:
            if rc not in seen_codes:
                seen_codes.add(rc)
                ordered_reason_codes.append(rc)

    decision_val = (
        decision.decision.value
        if isinstance(decision.decision, DecisionResult)
        else str(decision.decision)
    )

    return PublicGovernanceDecisionV1(
        schema_version="1",
        decision_id=decision.decision_id,
        decision=decision_val,
        contract_id=decision.contract_id,
        context=context,
        breaking=decision.breaking,
        required_version_bump=str(decision.required_version_bump),
        reason_codes=tuple(ordered_reason_codes),
        reasons=projected_reasons,
        validation=validation,
        policy=policy,
        evidence=evidence,
        changes=projected_changes,
    )


def serialize_public_governance_decision(
    decision: GovernanceDecision | PublicGovernanceDecisionV1,
    *,
    indent: int | None = None,
) -> str:
    """Serialize a governance decision into stable canonical JSON."""
    if isinstance(decision, GovernanceDecision):
        public_decision = to_public_governance_decision(decision)
    elif isinstance(decision, PublicGovernanceDecisionV1):
        public_decision = decision
    else:
        raise TypeError(
            f"Expected GovernanceDecision or PublicGovernanceDecisionV1, got {type(decision).__name__}"
        )

    dumped = public_decision.model_dump(mode="json", by_alias=True)
    return json.dumps(dumped, indent=indent, ensure_ascii=False)
