"""Unit tests for SemaPact GovernanceDecision Pydantic models and evaluator."""

from __future__ import annotations

import copy
from unittest import mock
import pytest
from pydantic import ValidationError as PydanticValidationError
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
from semapact.governance.models import ChangeEvidence, PolicyOutcome, ValidationOutcome
from semapact.lifecycle.merge_engine import MergeConflict
from semapact.orchestrator.pipeline import ContractPipeline, MergeResult, PipelineArtifacts


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


def test_governance_decision_allow_invariants_validator():
    """GovernanceDecision validates ALLOW invariants via @model_validator(mode='after')."""
    val = ValidationOutcome(valid=True)
    pol = PolicyOutcome(valid=True)
    evi = ChangeEvidence(has_changes=False, merge_conflicts_count=0)

    # Valid ALLOW decision
    GovernanceDecision(
        decision_id="id1",
        decision=DecisionResult.ALLOW,
        contract_id="c1",
        breaking=False,
        required_version_bump="none",
        validation=val,
        policy=pol,
        evidence=evi,
    )

    # ALLOW decision with breaking=True should fail invariant validation
    with pytest.raises(ValueError, match="ALLOW decision invariant violation"):
        GovernanceDecision(
            decision_id="id2",
            decision=DecisionResult.ALLOW,
            contract_id="c1",
            breaking=True,
            required_version_bump="none",
            validation=val,
            policy=pol,
            evidence=evi,
        )

    # ALLOW decision with required_version_bump="minor" should fail invariant validation
    with pytest.raises(ValueError, match="ALLOW decision invariant violation"):
        GovernanceDecision(
            decision_id="id3",
            decision=DecisionResult.ALLOW,
            contract_id="c1",
            breaking=False,
            required_version_bump="minor",
            validation=val,
            policy=pol,
            evidence=evi,
        )


def test_pydantic_model_strictness_and_extra_forbidden():
    """Pydantic model enforces strict types, forbidden extra fields, and immutability."""
    # Extra field forbidden
    with pytest.raises(PydanticValidationError):
        GovernanceReason(code="CODE", message="msg", extra_field="bad")

    # Strict bool type (string 'true' rejected)
    with pytest.raises(PydanticValidationError):
        ValidationOutcome(valid="true")  # type: ignore

    # Negative merge_conflicts_count rejected
    with pytest.raises(PydanticValidationError):
        ChangeEvidence(has_changes=True, merge_conflicts_count=-1)

    # Immutability (frozen)
    reason = GovernanceReason(code="CODE", message="msg")
    with pytest.raises(PydanticValidationError):
        reason.code = "NEW_CODE"  # type: ignore


def test_governance_decision_serialization_and_deserialization():
    """GovernanceDecision serializes with model_dump and deserializes with model_validate."""
    base = _make_contract()
    candidate = _make_contract()
    _get_schemas(candidate)[0].properties.append(
        SchemaProperty(name="note", logicalType="string", physicalType="varchar(100)", required=False)
    )

    decision = evaluate_governance_decision(base, candidate)
    dumped_json = decision.model_dump(mode="json")
    reconstructed = GovernanceDecision.model_validate(dumped_json)

    assert decision == reconstructed
    assert reconstructed.decision == DecisionResult.REVIEW
    assert reconstructed.required_version_bump == "minor"


def test_governance_decision_input_immutability():
    """Input contracts are untouched after evaluate_governance_decision."""
    base = _make_contract()
    candidate = _make_contract()

    base_copy = copy.deepcopy(base)
    candidate_copy = copy.deepcopy(candidate)

    evaluate_governance_decision(base, candidate)

    assert base == base_copy
    assert candidate == candidate_copy


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
    monkeypatch.setattr(
        ContractPipeline,
        "prepare_ci_cd_artifacts",
        lambda self, *args, **kwargs: PipelineArtifacts(
            merged_contract_path=tmp_path / "merged.yaml",
            ge_suite_path=tmp_path / "suite.json",
            ci_manifest_path=tmp_path / "manifest.json",
        ),
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
