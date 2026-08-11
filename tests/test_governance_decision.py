"""Unit tests for SemaPact GovernanceDecision and evaluator."""

from __future__ import annotations

import copy
from unittest import mock
import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.devops.ci_cd import evaluate_ci_gate
from semapact.governance import (
    DecisionResult,
    GovernanceDecision,
    GovernanceReason,
    evaluate_governance_decision,
)
from semapact.lifecycle.merge_engine import MergeConflict
from semapact.orchestrator.pipeline import ContractPipeline, MergeResult


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
    """decision_id is deterministic, insensitive to message text changes, but sensitive to code/path changes."""
    base = _make_contract()
    candidate = _make_contract()

    dec1 = evaluate_governance_decision(base, candidate)
    dec2 = evaluate_governance_decision(base, candidate)

    assert dec1.decision_id == dec2.decision_id

    # Create two decisions with different reason message text
    r1 = GovernanceReason(code="POLICY_BREAKING_CHANGE", message="Message text A", path="orders.id")
    r2 = GovernanceReason(code="POLICY_BREAKING_CHANGE", message="Message text B", path="orders.id")

    from semapact.governance.evaluator import _generate_decision_id
    id1 = _generate_decision_id(base, candidate, merge_conflicts=(), reasons=(r1,))
    id2 = _generate_decision_id(base, candidate, merge_conflicts=(), reasons=(r2,))

    assert id1 == id2, "Fingerprint should exclude human-readable message text"

    # Different code or path should produce different decision_id
    r3 = GovernanceReason(code="CONTRACT_ID_MISMATCH", message="Message text A", path="orders.id")
    id3 = _generate_decision_id(base, candidate, merge_conflicts=(), reasons=(r3,))
    assert id1 != id3, "Fingerprint should be sensitive to reason code"


def test_deserialization_fails_closed_and_raises_validation_error():
    """GovernanceDecision.from_dict raises ValueError on invalid or empty payloads."""
    with pytest.raises(ValueError, match="missing required field"):
        GovernanceDecision.from_dict({})

    with pytest.raises(ValueError, match="missing required field"):
        GovernanceDecision.from_dict({"decision": "ALLOW"})

    # evaluate_ci_gate fails closed on bad dicts
    gate_empty = evaluate_ci_gate({})
    assert gate_empty.allowed is False
    assert gate_empty.reason == "invalid_governance_decision"

    gate_bad_type = evaluate_ci_gate("not a dict")  # type: ignore
    assert gate_bad_type.allowed is False
    assert gate_bad_type.reason == "invalid_governance_decision"


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


def test_single_pass_governance_execution_spy(monkeypatch, tmp_path):
    """Verify ContractPipeline.run executes governance evaluation and helpers exactly once."""
    base = _make_contract()
    candidate = _make_contract()

    pipeline = ContractPipeline()

    monkeypatch.setattr(ContractPipeline, "import_schema", lambda *args, **kwargs: candidate)
    monkeypatch.setattr(type(pipeline.loader), "load", lambda self, _: base)
    monkeypatch.setattr(
        ContractPipeline,
        "merge_contract_updates",
        lambda *args, **kwargs: MergeResult(contract=candidate, conflicts=[]),
    )

    with mock.patch(
        "semapact.orchestrator.pipeline.evaluate_governance_decision",
        wraps=evaluate_governance_decision,
    ) as spy_eval:
        pipeline.run(
            source_type="sql",
            source="sql_folder",
            business_contract_path="examples/sample_odcs.yaml",
            merged_contract_output_path=str(tmp_path / "merged.yaml"),
            ge_suite_output_path=str(tmp_path / "suite.json"),
            ci_manifest_output_path=str(tmp_path / "manifest.json"),
        )
        assert spy_eval.call_count == 1
