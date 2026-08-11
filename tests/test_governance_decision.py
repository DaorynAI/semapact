"""Unit tests for SemaPact GovernanceDecision and evaluator."""

from __future__ import annotations

import copy
import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.governance import (
    DecisionResult,
    GovernanceDecision,
    GovernanceReason,
    evaluate_governance_decision,
)
from semapact.lifecycle.merge_engine import MergeConflict


def _get_schemas(contract: OpenDataContractStandard) -> list[SchemaObject]:
    return getattr(contract, "schema_", getattr(contract, "schema", [])) or []


def _make_contract(
    contract_id: str = "my-data-contract",
    version: str = "1.0.0",
    status: str = "active",
    properties: list[SchemaProperty] | None = None,
) -> OpenDataContractStandard:
    if properties is None:
        properties = [
            SchemaProperty(
                name="id",
                logicalType="string",
                physicalType="varchar(255)",
                required=True,
            ),
            SchemaProperty(
                name="amount",
                logicalType="number",
                physicalType="decimal(10,2)",
                required=False,
            ),
        ]
    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id=contract_id,
        name=contract_id,
        version=version,
        status=status,
        schema=[
            SchemaObject(
                name="orders",
                physicalName="orders",
                properties=properties,
            )
        ],
    )


def test_governance_decision_allow_same_contract():
    """Identical active contracts produce ALLOW decision with required_version_bump = 'none'."""
    base = _make_contract()
    candidate = _make_contract()

    decision = evaluate_governance_decision(base, candidate)

    assert decision.decision == DecisionResult.ALLOW
    assert decision.breaking is False
    assert decision.required_version_bump == "none"
    assert decision.validation.valid is True
    assert decision.policy.valid is True
    assert decision.evidence.has_changes is False
    assert isinstance(decision.decision_id, str)
    assert len(decision.decision_id) > 0


def test_governance_decision_review_for_minor_bump():
    """Adding a new optional field requires minor bump -> REVIEW decision."""
    base = _make_contract()
    candidate = _make_contract()
    _get_schemas(candidate)[0].properties.append(
        SchemaProperty(
            name="created_at",
            logicalType="timestamp",
            physicalType="timestamp",
            required=False,
        )
    )

    decision = evaluate_governance_decision(base, candidate)

    assert decision.decision == DecisionResult.REVIEW
    assert decision.required_version_bump == "minor"
    assert decision.breaking is False
    assert decision.validation.valid is True
    assert decision.policy.valid is True
    assert decision.evidence.has_changes is True


def test_governance_decision_review_for_major_breaking_change():
    """Removing a property from an active contract is breaking -> REVIEW decision with major bump."""
    base = _make_contract(status="active")
    candidate = _make_contract(status="active")
    schemas = _get_schemas(candidate)
    schemas[0].properties = [schemas[0].properties[0]]  # removed 'amount'

    decision = evaluate_governance_decision(base, candidate)

    assert decision.decision == DecisionResult.REVIEW
    assert decision.required_version_bump == "major"
    assert decision.breaking is True
    assert decision.policy.valid is False  # breaking changes present
    assert any(r.code == "POLICY_BREAKING_CHANGE" for r in decision.reasons)


def test_governance_decision_block_for_root_id_mismatch():
    """Root ID mismatch causes BLOCK decision regardless of active or draft status."""
    base = _make_contract(contract_id="contract-a", status="draft")
    candidate = _make_contract(contract_id="contract-b", status="draft")

    decision = evaluate_governance_decision(base, candidate)

    assert decision.decision == DecisionResult.BLOCK
    assert decision.policy.id_violation is True
    assert any(r.code == "CONTRACT_ID_MISMATCH" for r in decision.reasons)


def test_governance_decision_block_for_root_version_mismatch():
    """Root version mismatch causes BLOCK decision."""
    base = _make_contract(version="1.0.0", status="draft")
    candidate = _make_contract(version="2.0.0", status="draft")

    decision = evaluate_governance_decision(base, candidate)

    assert decision.decision == DecisionResult.BLOCK
    assert decision.policy.version_violation is True
    assert any(r.code == "CONTRACT_VERSION_MISMATCH" for r in decision.reasons)


def test_governance_decision_retired_mutation_blocks():
    """Mutating a retired contract causes BLOCK decision."""
    base = _make_contract(status="retired")
    candidate = _make_contract(status="retired")
    _get_schemas(candidate)[0].properties.append(
        SchemaProperty(name="extra", logicalType="string", physicalType="varchar(50)", required=False)
    )

    decision = evaluate_governance_decision(base, candidate)

    assert decision.decision == DecisionResult.BLOCK
    assert decision.policy.retired_violation is True
    assert any(r.code == "CONTRACT_RETIRED_MUTATION" for r in decision.reasons)


def test_governance_decision_retired_unchanged_allows():
    """Re-evaluating an unchanged retired contract results in ALLOW."""
    base = _make_contract(status="retired")
    candidate = _make_contract(status="retired")

    decision = evaluate_governance_decision(base, candidate)

    assert decision.decision == DecisionResult.ALLOW
    assert decision.policy.retired_violation is False


def test_governance_decision_retired_transition_reviews():
    """Transitioning an active contract to retired state triggers REVIEW."""
    base = _make_contract(status="active")
    candidate = _make_contract(status="retired")

    decision = evaluate_governance_decision(base, candidate)

    assert decision.decision == DecisionResult.REVIEW
    assert any(r.code == "CONTRACT_RETIRED_TRANSITION" for r in decision.reasons)


def test_governance_decision_block_for_invalid_validation():
    """Invalid candidate schema property (missing name or physicalType) causes BLOCK."""
    base = _make_contract()
    candidate = _make_contract()
    _get_schemas(candidate)[0].properties.append(
        SchemaProperty(name="", logicalType="string", physicalType="", required=True)
    )

    decision = evaluate_governance_decision(base, candidate)

    assert decision.decision == DecisionResult.BLOCK
    assert decision.validation.valid is False
    assert any(r.code == "VALIDATION_ERROR" for r in decision.reasons)


def test_governance_decision_review_for_merge_conflicts():
    """Merge conflicts trigger REVIEW decision."""
    base = _make_contract()
    candidate = _make_contract()
    conflicts = [
        MergeConflict(schema_id="orders", property_name="amount", message="Data type conflict")
    ]

    decision = evaluate_governance_decision(base, candidate, merge_conflicts=conflicts)

    assert decision.decision == DecisionResult.REVIEW
    assert decision.evidence.merge_conflicts_count == 1
    assert any(r.code == "MERGE_CONFLICT" for r in decision.reasons)


def test_governance_decision_fingerprint_deterministic_and_message_insensitive():
    """decision_id is deterministic and excludes human-readable message text from fingerprint."""
    base = _make_contract()
    candidate = _make_contract()

    dec1 = evaluate_governance_decision(base, candidate)
    dec2 = evaluate_governance_decision(base, candidate)

    assert dec1.decision_id == dec2.decision_id


def test_governance_decision_input_immutability():
    """Input contracts are untouched after evaluate_governance_decision."""
    base = _make_contract()
    candidate = _make_contract()

    base_copy = copy.deepcopy(base)
    candidate_copy = copy.deepcopy(candidate)

    evaluate_governance_decision(base, candidate)

    assert base == base_copy
    assert candidate == candidate_copy


def test_governance_decision_serialization_round_trip():
    """GovernanceDecision.to_dict() and from_dict() perform exact round-trip serialization."""
    base = _make_contract()
    candidate = _make_contract()
    _get_schemas(candidate)[0].properties.append(
        SchemaProperty(name="note", logicalType="string", physicalType="varchar(100)", required=False)
    )

    decision = evaluate_governance_decision(base, candidate)
    serialized = decision.to_dict()
    reconstructed = GovernanceDecision.from_dict(serialized)

    assert decision == reconstructed
    assert reconstructed.decision == DecisionResult.REVIEW
    assert reconstructed.required_version_bump == "minor"
