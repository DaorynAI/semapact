"""Authoritative governance decision evaluator."""

from __future__ import annotations

import json
import hashlib
import uuid
from typing import Sequence

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.core.release import classify_contract_change
from semapact.core.validator import ContractValidator
from semapact.governance.models import (
    ChangeEvidence,
    DecisionResult,
    GovernanceDecision,
    GovernanceReason,
    PolicyOutcome,
    ValidationOutcome,
)
from semapact.lifecycle.helpers import normalize_status
from semapact.lifecycle.merge_engine import MergeConflict
from semapact.lifecycle.policy import evaluate_merge_policy
from semapact.utils.schema_utils import contract_to_dict

SEMAPACT_GOVERNANCE_NAMESPACE = uuid.UUID("a9b8c7d6-e5f4-4321-8765-43210fedcba9")


def evaluate_governance_decision(
    base_contract: OpenDataContractStandard,
    candidate_contract: OpenDataContractStandard,
    *,
    merge_conflicts: Sequence[MergeConflict] = (),
) -> GovernanceDecision:
    """Evaluate an authoritative, deterministic governance decision for a contract change."""
    if not isinstance(base_contract, OpenDataContractStandard):
        raise TypeError(f"base_contract must be OpenDataContractStandard, got {type(base_contract).__name__}")
    if not isinstance(candidate_contract, OpenDataContractStandard):
        raise TypeError(f"candidate_contract must be OpenDataContractStandard, got {type(candidate_contract).__name__}")

    # 1. Validation outcome
    val_report = ContractValidator().validate(candidate_contract)
    val_issues = list(
        GovernanceReason(code="VALIDATION_ERROR", message=issue.message, path=issue.path)
        for issue in val_report.issues
    )

    # 2. Lifecycle policy outcome
    policy_eval = None
    try:
        policy_eval = evaluate_merge_policy(base_contract, candidate_contract)
    except Exception as e:
        val_issues.append(
            GovernanceReason(code="VALIDATION_ERROR", message=str(e), path="schema")
        )
        val_report = type(val_report)(valid=False, issues=val_report.issues)

    validation_outcome = ValidationOutcome(valid=val_report.valid and not bool(val_issues and not val_report.valid), issues=tuple(val_issues))

    if policy_eval is None:
        policy_eval = type("DummyPolicy", (), {"valid": False, "id_violation": False, "version_violation": False, "breaking_changes": []})()

    # 3. Version change classification (reusing policy_eval)
    try:
        change_assessment = classify_contract_change(
            base_contract, candidate_contract, policy_evaluation=policy_eval
        )
    except Exception:
        change_assessment = type("DummyAssessment", (), {"has_changes": True, "required_bump": "major", "breaking_changes": [], "reasons": ["Classification error"]})()

    # 4. Lifecycle status resolution for retired rules
    base_status = _resolve_status(base_contract)
    candidate_status = _resolve_status(candidate_contract)

    retired_mutation = base_status == "retired" and change_assessment.has_changes
    retired_transition = base_status != "retired" and candidate_status == "retired"

    # Collect policy violations
    policy_violations: list[GovernanceReason] = []
    if policy_eval.id_violation:
        policy_violations.append(
            GovernanceReason(
                code="CONTRACT_ID_MISMATCH",
                message="Contract ID mismatch: root ID is immutable.",
                path="id",
            )
        )
    if policy_eval.version_violation:
        policy_violations.append(
            GovernanceReason(
                code="CONTRACT_VERSION_MISMATCH",
                message="Contract version mismatch: contract versions are release-managed.",
                path="version",
            )
        )
    if retired_mutation:
        policy_violations.append(
            GovernanceReason(
                code="CONTRACT_RETIRED_MUTATION",
                message="Cannot modify a retired contract.",
                path="status",
            )
        )
    if retired_transition:
        policy_violations.append(
            GovernanceReason(
                code="CONTRACT_RETIRED_TRANSITION",
                message="Contract transition to retired status requires governance review.",
                path="status",
            )
        )
    for b in policy_eval.breaking_changes:
        policy_violations.append(
            GovernanceReason(
                code="POLICY_BREAKING_CHANGE",
                message=b.message,
                path=b.path,
            )
        )

    policy_outcome = PolicyOutcome(
        valid=policy_eval.valid and not retired_mutation,
        id_violation=policy_eval.id_violation,
        version_violation=policy_eval.version_violation,
        retired_violation=retired_mutation,
        violations=tuple(policy_violations),
    )

    # 5. Merge conflict reasons
    conflict_reasons: list[GovernanceReason] = []
    for c in merge_conflicts:
        path = c.path
        if not path and (c.schema_id or c.property_name):
            path = f"{c.schema_id or ''}.{c.property_name or ''}".strip(".")
        conflict_reasons.append(
            GovernanceReason(
                code="MERGE_CONFLICT",
                message=c.message or "Metadata merge conflict",
                path=path,
            )
        )

    # 6. Reasons deduplication and deterministic sorting
    raw_reasons: list[GovernanceReason] = []
    raw_reasons.extend(val_issues)
    raw_reasons.extend(policy_violations)
    raw_reasons.extend(conflict_reasons)
    for r_str in change_assessment.reasons:
        raw_reasons.append(GovernanceReason(code="CHANGE_ASSESSMENT", message=r_str))

    dedup_map: dict[tuple[str, str, str], GovernanceReason] = {}
    for r in raw_reasons:
        key = (r.code, r.path or "", r.message)
        if key not in dedup_map:
            dedup_map[key] = r

    sorted_reasons = tuple(
        dedup_map[key]
        for key in sorted(dedup_map.keys(), key=lambda k: (k[0], k[1], k[2]))
    )

    # 7. Decision Mapping
    is_blocking = (
        not validation_outcome.valid
        or policy_eval.id_violation
        or policy_eval.version_violation
        or retired_mutation
    )

    is_review = (
        not is_blocking
        and (
            retired_transition
            or bool(change_assessment.breaking_changes)
            or change_assessment.required_bump in ("minor", "major")
            or bool(merge_conflicts)
        )
    )

    if is_blocking:
        decision = DecisionResult.BLOCK
    elif is_review:
        decision = DecisionResult.REVIEW
    else:
        decision = DecisionResult.ALLOW

    # 8. Deterministic decision_id generation (excluding message string)
    evidence = ChangeEvidence(
        has_changes=change_assessment.has_changes,
        merge_conflicts_count=len(merge_conflicts),
    )

    contract_id = str(base_contract.id or candidate_contract.id or "")
    decision_id = _generate_decision_id(
        base_contract=base_contract,
        candidate_contract=candidate_contract,
        merge_conflicts=merge_conflicts,
        reasons=sorted_reasons,
    )

    return GovernanceDecision(
        decision_id=decision_id,
        decision=decision,
        contract_id=contract_id,
        breaking=bool(change_assessment.breaking_changes),
        required_version_bump=change_assessment.required_bump,
        reasons=sorted_reasons,
        validation=validation_outcome,
        policy=policy_outcome,
        evidence=evidence,
    )


def _resolve_status(contract: OpenDataContractStandard) -> str:
    val = getattr(contract, "status", None)
    if not val:
        for prop in getattr(contract, "customProperties", None) or []:
            if str(getattr(prop, "property", "")).lower() == "lifecyclestatus":
                val = str(getattr(prop, "value", ""))
                break
    return normalize_status(val, default="draft")


def _generate_decision_id(
    base_contract: OpenDataContractStandard,
    candidate_contract: OpenDataContractStandard,
    merge_conflicts: Sequence[MergeConflict],
    reasons: tuple[GovernanceReason, ...],
) -> str:
    base_fp = _contract_fingerprint(base_contract)
    candidate_fp = _contract_fingerprint(candidate_contract)
    conflict_paths = sorted(
        [c.path or f"{c.schema_id or ''}.{c.property_name or ''}" for c in merge_conflicts if c.path or c.schema_id or c.property_name]
    )
    reason_codes = sorted([(r.code, r.path or "") for r in reasons])

    payload = {
        "alg": "v1",
        "base": base_fp,
        "candidate": candidate_fp,
        "conflict_count": len(merge_conflicts),
        "conflict_paths": conflict_paths,
        "reason_codes": reason_codes,
    }

    payload_json = json.dumps(payload, sort_keys=True)
    return str(uuid.uuid5(SEMAPACT_GOVERNANCE_NAMESPACE, payload_json))


def _contract_fingerprint(contract: OpenDataContractStandard) -> str:
    d = contract_to_dict(contract)
    canonical_json = json.dumps(d, sort_keys=True)
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    cid = str(contract.id or "")
    version = str(contract.version or "")
    return f"{cid}:{version}:{digest[:16]}"
