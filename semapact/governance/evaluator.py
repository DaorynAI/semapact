"""Authoritative governance decision evaluator."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Sequence

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.change_context import ChangeContext
from semapact.core.release import ContractChangeAssessment, classify_contract_change
from semapact.core.validator import ContractValidator
from semapact.exceptions import ValidationError
from semapact.governance.models import (
    ChangeEvidence,
    DecisionResult,
    GovernanceDecision,
    GovernanceReason,
    PolicyOutcome,
    ValidationOutcome,
)
from semapact.governance_codes import GovernanceReasonCode, reason_severity
from semapact.lifecycle.changes import (
    GovernanceChange,
    GovernanceChangeEvidence,
    GovernanceChangeEvidenceSource,
    analyze_governance_changes,
)
from semapact.lifecycle.identity import validate_contract_identities
from semapact.lifecycle.merge_engine import MergeConflict
from semapact.lifecycle.policy import PolicyEvaluation, evaluate_merge_policy
from semapact.lifecycle.status import LifecycleStatus, resolve_contract_lifecycle
from semapact.utils.schema_utils import contract_to_dict


SEMAPACT_GOVERNANCE_NAMESPACE = uuid.UUID("a9b8c7d6-e5f4-4321-8765-43210fedcba9")


def evaluate_governance_decision(
    base_contract: OpenDataContractStandard,
    candidate_contract: OpenDataContractStandard,
    *,
    context: ChangeContext,
    merge_conflicts: Sequence[MergeConflict] = (),
) -> GovernanceDecision:
    """Evaluate an authoritative, deterministic governance decision for a contract change."""
    if not isinstance(base_contract, OpenDataContractStandard):
        raise TypeError(f"base_contract must be OpenDataContractStandard, got {type(base_contract).__name__}")
    if not isinstance(candidate_contract, OpenDataContractStandard):
        raise TypeError(f"candidate_contract must be OpenDataContractStandard, got {type(candidate_contract).__name__}")

    # 1. Validation outcome
    validation_outcome = _build_validation_outcome(candidate_contract)

    # 2. Canonical change analysis (computed once)
    try:
        raw_changes = analyze_governance_changes(base_contract, candidate_contract)
    except ValidationError:
        raw_changes = ()

    # 3. Policy outcome and change classification
    policy_outcome, change_assessment, retired_transition, annotated_changes = _build_policy_outcome(
        base_contract, candidate_contract, raw_changes=raw_changes
    )

    # 4. Attach merge conflict evidence to matching changes
    final_changes = _correlate_merge_conflicts(annotated_changes, merge_conflicts)

    # 5. Reason aggregation (deduplication & sorting)
    reasons = _aggregate_reasons(
        validation_outcome=validation_outcome,
        policy_outcome=policy_outcome,
        change_assessment=change_assessment,
        merge_conflicts=merge_conflicts,
    )

    # 6. Decision mapping
    decision_result = _determine_decision(
        validation_outcome=validation_outcome,
        policy_outcome=policy_outcome,
        change_assessment=change_assessment,
        merge_conflicts=merge_conflicts,
        retired_transition=retired_transition,
    )

    # 7. Fingerprint & Decision ID generation
    decision_id = _generate_decision_id(
        base_contract=base_contract,
        candidate_contract=candidate_contract,
        context=context,
        merge_conflicts=merge_conflicts,
        reasons=reasons,
    )

    contract_id = str(base_contract.id or candidate_contract.id or "")
    evidence = ChangeEvidence(
        has_changes=bool(raw_changes),
        merge_conflicts_count=len(merge_conflicts),
    )

    return GovernanceDecision(
        decision_id=decision_id,
        decision=decision_result,
        contract_id=contract_id,
        context=context,
        breaking=bool(change_assessment.breaking_changes),
        required_version_bump=change_assessment.required_bump,
        reasons=reasons,
        validation=validation_outcome,
        policy=policy_outcome,
        evidence=evidence,
        changes=final_changes,
    )


def _reason(
    code: GovernanceReasonCode,
    message: str,
    *,
    path: str | None = None,
    details: dict[str, Any] | None = None,
) -> GovernanceReason:
    """Build a reason using canonical registry severity and explicit evidence."""
    return GovernanceReason(
        code=code,
        message=message,
        path=path,
        severity=reason_severity(code),
        details=details or {},
    )


def _build_validation_outcome(candidate_contract: OpenDataContractStandard) -> ValidationOutcome:
    """Evaluate schema and field validation using ContractValidator and identity validation."""
    val_issues: list[GovernanceReason] = []
    valid = True
    try:
        validate_contract_identities(candidate_contract)
        val_report = ContractValidator().validate(candidate_contract)
        for issue in val_report.issues:
            val_issues.append(
                _reason(
                    GovernanceReasonCode.VALIDATION_FAILED,
                    issue.message,
                    path=issue.path,
                )
            )
        valid = val_report.valid and not bool(val_issues)
    except ValidationError as exc:
        val_issues.append(
            _reason(
                GovernanceReasonCode.VALIDATION_FAILED,
                str(exc),
                path="schema",
            )
        )
        valid = False

    return ValidationOutcome(valid=valid, issues=tuple(val_issues))


def _correlate_merge_conflicts(
    changes: Sequence[GovernanceChange],
    merge_conflicts: Sequence[MergeConflict],
) -> tuple[GovernanceChange, ...]:
    """Attach typed merge-conflict evidence to canonical changes matching conflict paths."""
    if not merge_conflicts:
        return tuple(changes)

    conflict_map: dict[str, list[MergeConflict]] = {}
    for c in merge_conflicts:
        keys: list[str] = []
        if c.path:
            keys.append(c.path.strip().lower())
        if c.schema_id and c.property_name:
            keys.append(f"{c.schema_id.strip().lower()}.{c.property_name.strip().lower()}")
            keys.append(
                f"schema[{c.schema_id.strip().lower()}].properties[{c.property_name.strip().lower()}]"
            )
        for k in keys:
            conflict_map.setdefault(k, []).append(c)

    correlated: list[GovernanceChange] = []
    for change in changes:
        matched_conflicts: list[MergeConflict] = []
        change_path_lower = change.path.strip().lower()
        if change_path_lower in conflict_map:
            matched_conflicts.extend(conflict_map[change_path_lower])
        ident_key = ".".join(change.identity).lower()
        if ident_key in conflict_map:
            matched_conflicts.extend(conflict_map[ident_key])

        if matched_conflicts:
            ev_list = list(change.evidence)
            for mc in matched_conflicts:
                code_val = str(mc.rule or "merge_conflict")
                ev_obj = GovernanceChangeEvidence(
                    source=GovernanceChangeEvidenceSource.MERGE_CONFLICT,
                    code=code_val,
                )
                if ev_obj not in ev_list:
                    ev_list.append(ev_obj)
            sorted_ev = tuple(sorted(ev_list, key=lambda e: (e.source.value, e.code)))
            correlated.append(change.model_copy(update={"evidence": sorted_ev}))
        else:
            correlated.append(change)

    return tuple(correlated)


def _build_policy_outcome(
    base_contract: OpenDataContractStandard,
    candidate_contract: OpenDataContractStandard,
    *,
    raw_changes: tuple[GovernanceChange, ...],
) -> tuple[PolicyOutcome, ContractChangeAssessment, bool, tuple[GovernanceChange, ...]]:
    """Evaluate lifecycle policy rules and change classification using canonical changes."""
    try:
        policy_eval: PolicyEvaluation = evaluate_merge_policy(
            base_contract, candidate_contract, changes=raw_changes
        )
    except ValidationError:
        policy_eval = PolicyEvaluation(valid=False, annotated_changes=raw_changes)

    annotated_changes = policy_eval.annotated_changes or raw_changes

    try:
        change_assessment: ContractChangeAssessment = classify_contract_change(
            base_contract, candidate_contract, changes=annotated_changes, policy_evaluation=policy_eval
        )
    except ValidationError:
        change_assessment = ContractChangeAssessment(
            has_changes=bool(raw_changes),
            required_bump="none",
            breaking_changes=[],
            reasons=["Validation error"],
        )

    try:
        base_status = resolve_contract_lifecycle(base_contract)
    except (ValueError, TypeError):
        base_status = LifecycleStatus.DRAFT

    try:
        candidate_status = resolve_contract_lifecycle(candidate_contract)
    except (ValueError, TypeError):
        candidate_status = LifecycleStatus.DRAFT

    retired_mutation = base_status is LifecycleStatus.RETIRED and bool(raw_changes)
    retired_transition = (
        base_status is not LifecycleStatus.RETIRED
        and candidate_status is LifecycleStatus.RETIRED
    )

    policy_violations: list[GovernanceReason] = [
        _reason(b.code, b.message, path=b.path)
        for b in policy_eval.breaking_changes
    ]

    if retired_mutation:
        policy_violations.append(
            _reason(
                GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED,
                "Cannot modify a retired contract.",
                path="status",
            )
        )
    if retired_transition:
        policy_violations.append(
            _reason(
                GovernanceReasonCode.CONTRACT_RETIRED_TRANSITION,
                "Contract transition to retired status requires governance review.",
                path="status",
            )
        )

    policy_outcome = PolicyOutcome(
        valid=policy_eval.valid and not retired_mutation,
        id_violation=policy_eval.id_violation,
        version_violation=policy_eval.version_violation,
        retired_violation=retired_mutation,
        violations=tuple(policy_violations),
        breaking_changes=tuple(policy_eval.breaking_changes),
    )

    return policy_outcome, change_assessment, retired_transition, annotated_changes


def _aggregate_reasons(
    validation_outcome: ValidationOutcome,
    policy_outcome: PolicyOutcome,
    change_assessment: ContractChangeAssessment,
    merge_conflicts: Sequence[MergeConflict],
) -> tuple[GovernanceReason, ...]:
    """Aggregate, deduplicate, and deterministically sort all governance reasons."""
    raw_reasons: list[GovernanceReason] = []
    raw_reasons.extend(validation_outcome.issues)
    raw_reasons.extend(policy_outcome.violations)

    for c in merge_conflicts:
        path = c.path
        if not path and (c.schema_id or c.property_name):
            path = f"{c.schema_id or ''}.{c.property_name or ''}".strip(".")
        details = {
            key: value
            for key, value in (
                ("rule", c.rule),
                ("schema_id", c.schema_id),
                ("property_name", c.property_name),
            )
            if value is not None
        }
        raw_reasons.append(
            _reason(
                GovernanceReasonCode.MERGE_CONFLICT,
                c.message or "Metadata merge conflict",
                path=path,
                details=details,
            )
        )

    for r_str in change_assessment.reasons:
        raw_reasons.append(
            _reason(GovernanceReasonCode.CHANGE_ASSESSMENT, r_str)
        )

    dedup_map: dict[tuple[str, str, str], GovernanceReason] = {}
    for r in raw_reasons:
        key = (r.code.value, r.path or "", r.message)
        if key not in dedup_map:
            dedup_map[key] = r

    return tuple(
        dedup_map[key]
        for key in sorted(dedup_map.keys(), key=lambda k: (k[0], k[1], k[2]))
    )


def _determine_decision(
    validation_outcome: ValidationOutcome,
    policy_outcome: PolicyOutcome,
    change_assessment: ContractChangeAssessment,
    merge_conflicts: Sequence[MergeConflict],
    retired_transition: bool,
) -> DecisionResult:
    """Map outcome signals to BLOCK, REVIEW, or ALLOW decision."""
    is_blocking = (
        not validation_outcome.valid
        or policy_outcome.id_violation
        or policy_outcome.version_violation
        or policy_outcome.retired_violation
    )

    if is_blocking:
        return DecisionResult.BLOCK

    is_review = (
        retired_transition
        or bool(change_assessment.breaking_changes)
        or change_assessment.required_bump in ("minor", "major")
        or bool(merge_conflicts)
    )

    if is_review:
        return DecisionResult.REVIEW

    return DecisionResult.ALLOW




def _generate_decision_id(
    base_contract: OpenDataContractStandard,
    candidate_contract: OpenDataContractStandard,
    context: ChangeContext,
    merge_conflicts: Sequence[MergeConflict],
    reasons: tuple[GovernanceReason, ...],
) -> str:
    """Generate a deterministic UUID5 decision_id excluding human-readable messages."""
    base_fp = _contract_fingerprint(base_contract)
    candidate_fp = _contract_fingerprint(candidate_contract)
    conflict_paths = sorted(
        [c.path or f"{c.schema_id or ''}.{c.property_name or ''}" for c in merge_conflicts if c.path or c.schema_id or c.property_name]
    )
    reason_codes = sorted([(r.code.value, r.path or "") for r in reasons])

    payload = {
        "alg": "v1",
        "base": base_fp,
        "candidate": candidate_fp,
        "effective_date": context.effective_date.isoformat(),
        "conflict_count": len(merge_conflicts),
        "conflict_paths": conflict_paths,
        "reason_codes": reason_codes,
    }

    payload_json = json.dumps(payload, sort_keys=True)
    return str(uuid.uuid5(SEMAPACT_GOVERNANCE_NAMESPACE, payload_json))


def _contract_fingerprint(contract: OpenDataContractStandard) -> str:
    """Compute a canonical digest fingerprint for an OpenDataContractStandard instance."""
    d = contract_to_dict(contract)
    canonical_json = json.dumps(d, sort_keys=True)
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    cid = str(contract.id or "")
    version = str(contract.version or "")
    return f"{cid}:{version}:{digest[:16]}"
