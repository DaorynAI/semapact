"""Stable, versioned public contract for SemaPact governance decisions (v1)."""

from __future__ import annotations

import json
from typing import Any, Literal, cast
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, JsonValue

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


# ==============================================================================
# Public Protocol Vocabulary Literals
# ==============================================================================

PublicDecisionResult = Literal["ALLOW", "REVIEW", "BLOCK"]
PublicRequiredVersionBump = Literal["none", "patch", "minor", "major"]
PublicSeverity = Literal["ERROR", "WARNING", "INFO"]
PublicChangeType = Literal["ADD", "REMOVE", "MODIFY", "DEPRECATE"]
PublicEntityType = Literal[
    "CONTRACT",
    "SCHEMA",
    "PROPERTY",
    "RELATIONSHIP",
    "QUALITY",
]
PublicChangeDomain = Literal[
    "IDENTITY",
    "VERSION",
    "LIFECYCLE",
    "STRUCTURE",
    "RELATIONSHIP",
    "QUALITY",
    "METADATA",
]
PublicEvidenceSource = Literal["MERGE_CONFLICT"]


# ==============================================================================
# Protocol Mappers (Internal Domain Enum -> Public Protocol Literal)
# ==============================================================================

_DECISION_MAP: dict[DecisionResult, PublicDecisionResult] = {
    DecisionResult.ALLOW: "ALLOW",
    DecisionResult.REVIEW: "REVIEW",
    DecisionResult.BLOCK: "BLOCK",
}

_SEVERITY_MAP: dict[GovernanceSeverity, PublicSeverity] = {
    GovernanceSeverity.ERROR: "ERROR",
    GovernanceSeverity.WARNING: "WARNING",
    GovernanceSeverity.INFO: "INFO",
}

_CHANGE_TYPE_MAP: dict[GovernanceChangeType, PublicChangeType] = {
    GovernanceChangeType.ADD: "ADD",
    GovernanceChangeType.REMOVE: "REMOVE",
    GovernanceChangeType.MODIFY: "MODIFY",
    GovernanceChangeType.DEPRECATE: "DEPRECATE",
}

_ENTITY_TYPE_MAP: dict[GovernanceEntityType, PublicEntityType] = {
    GovernanceEntityType.CONTRACT: "CONTRACT",
    GovernanceEntityType.SCHEMA: "SCHEMA",
    GovernanceEntityType.PROPERTY: "PROPERTY",
    GovernanceEntityType.RELATIONSHIP: "RELATIONSHIP",
    GovernanceEntityType.QUALITY: "QUALITY",
}

_DOMAIN_MAP: dict[GovernanceChangeDomain, PublicChangeDomain] = {
    GovernanceChangeDomain.IDENTITY: "IDENTITY",
    GovernanceChangeDomain.VERSION: "VERSION",
    GovernanceChangeDomain.LIFECYCLE: "LIFECYCLE",
    GovernanceChangeDomain.STRUCTURE: "STRUCTURE",
    GovernanceChangeDomain.RELATIONSHIP: "RELATIONSHIP",
    GovernanceChangeDomain.QUALITY: "QUALITY",
    GovernanceChangeDomain.METADATA: "METADATA",
}

_EVIDENCE_SOURCE_MAP: dict[GovernanceChangeEvidenceSource, PublicEvidenceSource] = {
    GovernanceChangeEvidenceSource.MERGE_CONFLICT: "MERGE_CONFLICT",
}

_REQUIRED_BUMP_MAP: dict[str, PublicRequiredVersionBump] = {
    "none": "none",
    "patch": "patch",
    "minor": "minor",
    "major": "major",
}


def _map_decision(decision: DecisionResult | str) -> PublicDecisionResult:
    if isinstance(decision, DecisionResult):
        return _DECISION_MAP[decision]
    val = str(decision)
    if val in {"ALLOW", "REVIEW", "BLOCK"}:
        return cast(PublicDecisionResult, val)
    raise ValueError(f"Invalid decision for public contract: {decision}")


def _map_severity(severity: GovernanceSeverity | str) -> PublicSeverity:
    if isinstance(severity, GovernanceSeverity):
        return _SEVERITY_MAP[severity]
    val = str(severity)
    if val in {"ERROR", "WARNING", "INFO"}:
        return cast(PublicSeverity, val)
    raise ValueError(f"Invalid severity for public contract: {severity}")


def _map_change_type(change_type: GovernanceChangeType | str) -> PublicChangeType:
    if isinstance(change_type, GovernanceChangeType):
        return _CHANGE_TYPE_MAP[change_type]
    val = str(change_type)
    if val in {"ADD", "REMOVE", "MODIFY", "DEPRECATE"}:
        return cast(PublicChangeType, val)
    raise ValueError(f"Invalid change_type for public contract: {change_type}")


def _map_entity_type(entity_type: GovernanceEntityType | str) -> PublicEntityType:
    if isinstance(entity_type, GovernanceEntityType):
        return _ENTITY_TYPE_MAP[entity_type]
    val = str(entity_type)
    if val in {"CONTRACT", "SCHEMA", "PROPERTY", "RELATIONSHIP", "QUALITY"}:
        return cast(PublicEntityType, val)
    raise ValueError(f"Invalid entity_type for public contract: {entity_type}")


def _map_domain(domain: GovernanceChangeDomain | str) -> PublicChangeDomain:
    if isinstance(domain, GovernanceChangeDomain):
        return _DOMAIN_MAP[domain]
    val = str(domain)
    if val in {"IDENTITY", "VERSION", "LIFECYCLE", "STRUCTURE", "RELATIONSHIP", "QUALITY", "METADATA"}:
        return cast(PublicChangeDomain, val)
    raise ValueError(f"Invalid domain for public contract: {domain}")


def _map_evidence_source(source: GovernanceChangeEvidenceSource | str) -> PublicEvidenceSource:
    if isinstance(source, GovernanceChangeEvidenceSource):
        return _EVIDENCE_SOURCE_MAP[source]
    val = str(source)
    if val in {"MERGE_CONFLICT"}:
        return cast(PublicEvidenceSource, val)
    raise ValueError(f"Invalid evidence source for public contract: {source}")


def _map_required_bump(bump: str) -> PublicRequiredVersionBump:
    if bump in _REQUIRED_BUMP_MAP:
        return _REQUIRED_BUMP_MAP[bump]
    raise ValueError(f"Invalid required_version_bump for public contract: {bump}")


# ==============================================================================
# Public Models
# ==============================================================================

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

    effective_date: str = Field(
        validation_alias=AliasChoices("effective_date", "effectiveDate"),
        serialization_alias="effectiveDate",
    )


class PublicGovernanceReasonV1(PublicGovernanceModel):
    """Public structured reason for a governance outcome or violation."""

    code: str
    severity: PublicSeverity
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
    id_violation: bool = Field(
        default=False,
        validation_alias=AliasChoices("id_violation", "idViolation"),
        serialization_alias="idViolation",
    )
    version_violation: bool = Field(
        default=False,
        validation_alias=AliasChoices("version_violation", "versionViolation"),
        serialization_alias="versionViolation",
    )
    retired_violation: bool = Field(
        default=False,
        validation_alias=AliasChoices("retired_violation", "retiredViolation"),
        serialization_alias="retiredViolation",
    )
    violations: tuple[PublicGovernanceReasonV1, ...] = ()


class PublicChangeEvidenceV1(PublicGovernanceModel):
    """Public summarized evidence for contract mutations."""

    has_changes: bool = Field(
        default=False,
        validation_alias=AliasChoices("has_changes", "hasChanges"),
        serialization_alias="hasChanges",
    )
    merge_conflicts_count: int = Field(
        default=0,
        validation_alias=AliasChoices("merge_conflicts_count", "mergeConflictsCount"),
        serialization_alias="mergeConflictsCount",
    )


class PublicGovernanceChangeEvidenceV1(PublicGovernanceModel):
    """Public evidence source supporting a semantic change."""

    source: PublicEvidenceSource
    code: str


class PublicGovernanceChangeV1(PublicGovernanceModel):
    """Public canonical representation of a single semantic contract change."""

    change_type: PublicChangeType = Field(
        validation_alias=AliasChoices("change_type", "changeType"),
        serialization_alias="changeType",
    )
    entity_type: PublicEntityType = Field(
        validation_alias=AliasChoices("entity_type", "entityType"),
        serialization_alias="entityType",
    )
    identity: tuple[str, ...]
    path: str
    field: str | None = None
    before: JsonValue | None = None
    after: JsonValue | None = None
    domain: PublicChangeDomain
    breaking: bool = False
    reason_codes: tuple[str, ...] = Field(
        default=(),
        validation_alias=AliasChoices("reason_codes", "reasonCodes"),
        serialization_alias="reasonCodes",
    )
    evidence: tuple[PublicGovernanceChangeEvidenceV1, ...] = ()


class PublicGovernanceDecisionV1(PublicGovernanceModel):
    """Authoritative, versioned public contract for a SemaPact governance decision."""

    schema_version: Literal["1"] = Field(
        default="1",
        validation_alias=AliasChoices("schema_version", "schemaVersion"),
        serialization_alias="schemaVersion",
    )
    decision_id: str = Field(
        validation_alias=AliasChoices("decision_id", "decisionId"),
        serialization_alias="decisionId",
    )
    decision: PublicDecisionResult
    contract_id: str = Field(
        validation_alias=AliasChoices("contract_id", "contractId"),
        serialization_alias="contractId",
    )
    context: PublicChangeContextV1
    breaking: bool
    required_version_bump: PublicRequiredVersionBump = Field(
        validation_alias=AliasChoices("required_version_bump", "requiredVersionBump"),
        serialization_alias="requiredVersionBump",
    )
    reason_codes: tuple[str, ...] = Field(
        default=(),
        validation_alias=AliasChoices("reason_codes", "reasonCodes"),
        serialization_alias="reasonCodes",
    )
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
        """Serialize to deterministic canonical JSON with sorted keys."""
        return serialize_public_governance_decision(self, indent=indent)

    def to_canonical_dict(self) -> dict[str, Any]:
        """Convert to JSON-compatible dictionary with external camelCase field names."""
        return self.model_dump(mode="json", by_alias=True)


# ==============================================================================
# Explicit Projection Functions
# ==============================================================================

def _project_reason(reason: GovernanceReason) -> PublicGovernanceReasonV1:
    """Project internal GovernanceReason to PublicGovernanceReasonV1."""
    code_val = reason.code.value if isinstance(reason.code, GovernanceReasonCode) else str(reason.code)
    severity_val = _map_severity(reason.severity)
    details_copy = {k: reason.details[k] for k in sorted(reason.details)} if reason.details else {}
    return PublicGovernanceReasonV1(
        code=code_val,
        severity=severity_val,
        message=reason.message,
        path=reason.path,
        details=details_copy,
    )


def _project_change_evidence(evidence: GovernanceChangeEvidence) -> PublicGovernanceChangeEvidenceV1:
    """Project internal GovernanceChangeEvidence to PublicGovernanceChangeEvidenceV1."""
    source_val = _map_evidence_source(evidence.source)
    return PublicGovernanceChangeEvidenceV1(
        source=source_val,
        code=evidence.code,
    )


def _project_change(change: GovernanceChange) -> PublicGovernanceChangeV1:
    """Project internal GovernanceChange to PublicGovernanceChangeV1 with deterministic sorting."""
    change_type_val = _map_change_type(change.change_type)
    entity_type_val = _map_entity_type(change.entity_type)
    domain_val = _map_domain(change.domain)
    projected_evidence = tuple(
        sorted(
            (_project_change_evidence(ev) for ev in change.evidence),
            key=lambda e: (e.source, e.code),
        )
    )
    reason_codes_val = tuple(
        sorted({
            rc.value if isinstance(rc, GovernanceReasonCode) else str(rc)
            for rc in change.reason_codes
        })
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

    # 7. Aggregate stable unique reason codes in deterministic alphabetical order
    all_reason_codes: set[str] = set()
    for r in projected_reasons:
        all_reason_codes.add(r.code)
    for c in projected_changes:
        all_reason_codes.update(c.reason_codes)

    decision_val = _map_decision(decision.decision)
    bump_val = _map_required_bump(str(decision.required_version_bump))

    return PublicGovernanceDecisionV1(
        schema_version="1",
        decision_id=decision.decision_id,
        decision=decision_val,
        contract_id=decision.contract_id,
        context=context,
        breaking=decision.breaking,
        required_version_bump=bump_val,
        reason_codes=tuple(sorted(all_reason_codes)),
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
    """Serialize a governance decision into stable canonical JSON with sorted keys."""
    if isinstance(decision, GovernanceDecision):
        public_decision = to_public_governance_decision(decision)
    elif isinstance(decision, PublicGovernanceDecisionV1):
        public_decision = decision
    else:
        raise TypeError(
            f"Expected GovernanceDecision or PublicGovernanceDecisionV1, got {type(decision).__name__}"
        )

    dumped = public_decision.model_dump(mode="json", by_alias=True)
    return json.dumps(dumped, indent=indent, sort_keys=True, ensure_ascii=False)
