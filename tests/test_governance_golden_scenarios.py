"""Deterministic golden regression test suite for SemaPact governance decisions.

Freezes authoritative M0 governance semantics across lifecycle, breaking-change
classification, version bump recommendation, reason codes, canonical identity,
deterministic decision IDs, and public GovernanceDecision (v1) JSON serialization.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import pytest
import yaml

from open_data_contract_standard.model import OpenDataContractStandard
from semapact.change_context import ChangeContext
from semapact.core.release import RequiredBump
from semapact.governance import (
    DecisionResult,
    evaluate_governance_decision,
    serialize_public_governance_decision,
    to_public_governance_decision,
)
from semapact.governance_codes import GovernanceReasonCode
from semapact.lifecycle.merge_engine import MergeConflict

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "governance_scenarios"
TEST_CONTEXT = ChangeContext(effective_date=date(2026, 1, 1))


@dataclass(frozen=True)
class GovernanceGoldenScenario:
    """Descriptor for a single golden regression scenario."""

    name: str
    expected_decision: DecisionResult
    expected_bump: RequiredBump
    expected_breaking: bool
    expected_reason_codes: frozenset[GovernanceReasonCode]
    merge_conflicts: tuple[MergeConflict, ...] = ()
    expected_policy_valid: bool | None = None
    expected_validation_valid: bool | None = None


# Authoritative semantic expectation matrix for all 23 golden scenarios
SCENARIO_MATRIX: tuple[GovernanceGoldenScenario, ...] = (
    # 1. No change
    GovernanceGoldenScenario(
        name="no_change",
        expected_decision=DecisionResult.ALLOW,
        expected_bump="none",
        expected_breaking=False,
        expected_reason_codes=frozenset({GovernanceReasonCode.CHANGE_ASSESSMENT}),
        expected_policy_valid=True,
        expected_validation_valid=True,
    ),
    # 2. Descriptive metadata only
    GovernanceGoldenScenario(
        name="descriptive_metadata_only",
        expected_decision=DecisionResult.ALLOW,
        expected_bump="none",
        expected_breaking=False,
        expected_reason_codes=frozenset({GovernanceReasonCode.CHANGE_ASSESSMENT}),
        expected_policy_valid=True,
        expected_validation_valid=True,
    ),
    # 3. Property addition
    GovernanceGoldenScenario(
        name="property_addition",
        expected_decision=DecisionResult.REVIEW,
        expected_bump="minor",
        expected_breaking=False,
        expected_reason_codes=frozenset({GovernanceReasonCode.CHANGE_ASSESSMENT}),
        expected_policy_valid=True,
        expected_validation_valid=True,
    ),
    # 4. Schema addition
    GovernanceGoldenScenario(
        name="schema_addition",
        expected_decision=DecisionResult.REVIEW,
        expected_bump="minor",
        expected_breaking=False,
        expected_reason_codes=frozenset({GovernanceReasonCode.CHANGE_ASSESSMENT}),
        expected_policy_valid=True,
        expected_validation_valid=True,
    ),
    # 5. Property removal
    GovernanceGoldenScenario(
        name="property_removal",
        expected_decision=DecisionResult.REVIEW,
        expected_bump="major",
        expected_breaking=True,
        expected_reason_codes=frozenset({
            GovernanceReasonCode.CHANGE_ASSESSMENT,
            GovernanceReasonCode.PROPERTY_REMOVED,
        }),
        expected_policy_valid=False,
        expected_validation_valid=True,
    ),
    # 6. Schema removal
    GovernanceGoldenScenario(
        name="schema_removal",
        expected_decision=DecisionResult.REVIEW,
        expected_bump="major",
        expected_breaking=True,
        expected_reason_codes=frozenset({
            GovernanceReasonCode.CHANGE_ASSESSMENT,
            GovernanceReasonCode.SCHEMA_REMOVED,
        }),
        expected_policy_valid=False,
        expected_validation_valid=True,
    ),
    # 7. Logical type change
    GovernanceGoldenScenario(
        name="logical_type_change",
        expected_decision=DecisionResult.REVIEW,
        expected_bump="major",
        expected_breaking=True,
        expected_reason_codes=frozenset({
            GovernanceReasonCode.CHANGE_ASSESSMENT,
            GovernanceReasonCode.LOGICAL_TYPE_CHANGED,
        }),
        expected_policy_valid=False,
        expected_validation_valid=True,
    ),
    # 8. Physical type narrowing
    GovernanceGoldenScenario(
        name="physical_type_narrowing",
        expected_decision=DecisionResult.REVIEW,
        expected_bump="major",
        expected_breaking=True,
        expected_reason_codes=frozenset({
            GovernanceReasonCode.CHANGE_ASSESSMENT,
            GovernanceReasonCode.PHYSICAL_TYPE_NARROWED,
        }),
        expected_policy_valid=False,
        expected_validation_valid=True,
    ),
    # 9. Decimal precision reduction
    GovernanceGoldenScenario(
        name="decimal_precision_reduction",
        expected_decision=DecisionResult.REVIEW,
        expected_bump="major",
        expected_breaking=True,
        expected_reason_codes=frozenset({
            GovernanceReasonCode.CHANGE_ASSESSMENT,
            GovernanceReasonCode.DECIMAL_PRECISION_REDUCED,
        }),
        expected_policy_valid=False,
        expected_validation_valid=True,
    ),
    # 10. Decimal scale reduction
    GovernanceGoldenScenario(
        name="decimal_scale_reduction",
        expected_decision=DecisionResult.REVIEW,
        expected_bump="major",
        expected_breaking=True,
        expected_reason_codes=frozenset({
            GovernanceReasonCode.CHANGE_ASSESSMENT,
            GovernanceReasonCode.DECIMAL_SCALE_REDUCED,
        }),
        expected_policy_valid=False,
        expected_validation_valid=True,
    ),
    # 11. Decimal widening
    GovernanceGoldenScenario(
        name="decimal_widening",
        expected_decision=DecisionResult.REVIEW,
        expected_bump="minor",
        expected_breaking=False,
        expected_reason_codes=frozenset({GovernanceReasonCode.CHANGE_ASSESSMENT}),
        expected_policy_valid=True,
        expected_validation_valid=True,
    ),
    # 12. Required tightening
    GovernanceGoldenScenario(
        name="required_tightening",
        expected_decision=DecisionResult.REVIEW,
        expected_bump="major",
        expected_breaking=True,
        expected_reason_codes=frozenset({
            GovernanceReasonCode.CHANGE_ASSESSMENT,
            GovernanceReasonCode.REQUIRED_TIGHTENED,
        }),
        expected_policy_valid=False,
        expected_validation_valid=True,
    ),
    # 13. Enum reduction (authoritative ODCS model ignores extra enum in YAML)
    GovernanceGoldenScenario(
        name="enum_reduction",
        expected_decision=DecisionResult.ALLOW,
        expected_bump="none",
        expected_breaking=False,
        expected_reason_codes=frozenset({GovernanceReasonCode.CHANGE_ASSESSMENT}),
        expected_policy_valid=True,
        expected_validation_valid=True,
    ),
    # 14. Relationship removal
    GovernanceGoldenScenario(
        name="relationship_removal",
        expected_decision=DecisionResult.REVIEW,
        expected_bump="major",
        expected_breaking=True,
        expected_reason_codes=frozenset({
            GovernanceReasonCode.CHANGE_ASSESSMENT,
            GovernanceReasonCode.RELATIONSHIP_REMOVED,
        }),
        expected_policy_valid=False,
        expected_validation_valid=True,
    ),
    # 15. Draft entity change
    GovernanceGoldenScenario(
        name="draft_entity_change",
        expected_decision=DecisionResult.REVIEW,
        expected_bump="minor",
        expected_breaking=False,
        expected_reason_codes=frozenset({GovernanceReasonCode.CHANGE_ASSESSMENT}),
        expected_policy_valid=True,
        expected_validation_valid=True,
    ),
    # 16. Deprecated entity change
    GovernanceGoldenScenario(
        name="deprecated_entity_change",
        expected_decision=DecisionResult.REVIEW,
        expected_bump="minor",
        expected_breaking=False,
        expected_reason_codes=frozenset({GovernanceReasonCode.CHANGE_ASSESSMENT}),
        expected_policy_valid=True,
        expected_validation_valid=True,
    ),
    # 17. Active to retired transition
    GovernanceGoldenScenario(
        name="active_to_retired_transition",
        expected_decision=DecisionResult.REVIEW,
        expected_bump="none",
        expected_breaking=False,
        expected_reason_codes=frozenset({
            GovernanceReasonCode.CHANGE_ASSESSMENT,
            GovernanceReasonCode.CONTRACT_RETIRED_TRANSITION,
        }),
        expected_policy_valid=True,
        expected_validation_valid=True,
    ),
    # 18. Retired contract mutation
    GovernanceGoldenScenario(
        name="retired_contract_mutation",
        expected_decision=DecisionResult.BLOCK,
        expected_bump="none",
        expected_breaking=False,
        expected_reason_codes=frozenset({
            GovernanceReasonCode.CHANGE_ASSESSMENT,
            GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED,
        }),
        expected_policy_valid=False,
        expected_validation_valid=True,
    ),
    # 19. Contract ID change
    GovernanceGoldenScenario(
        name="contract_id_change",
        expected_decision=DecisionResult.BLOCK,
        expected_bump="major",
        expected_breaking=True,
        expected_reason_codes=frozenset({
            GovernanceReasonCode.CHANGE_ASSESSMENT,
            GovernanceReasonCode.CONTRACT_ID_CHANGED,
        }),
        expected_policy_valid=False,
        expected_validation_valid=True,
    ),
    # 20. Manual version change
    GovernanceGoldenScenario(
        name="manual_version_change",
        expected_decision=DecisionResult.BLOCK,
        expected_bump="major",
        expected_breaking=True,
        expected_reason_codes=frozenset({
            GovernanceReasonCode.CHANGE_ASSESSMENT,
            GovernanceReasonCode.CONTRACT_VERSION_MANUALLY_CHANGED,
        }),
        expected_policy_valid=False,
        expected_validation_valid=True,
    ),
    # 21. Physical name identity stability
    GovernanceGoldenScenario(
        name="physical_name_identity_stability",
        expected_decision=DecisionResult.REVIEW,
        expected_bump="minor",
        expected_breaking=False,
        expected_reason_codes=frozenset({GovernanceReasonCode.CHANGE_ASSESSMENT}),
        expected_policy_valid=True,
        expected_validation_valid=True,
    ),
    # 22. Validation failure
    GovernanceGoldenScenario(
        name="validation_failure",
        expected_decision=DecisionResult.BLOCK,
        expected_bump="none",
        expected_breaking=False,
        expected_reason_codes=frozenset({
            GovernanceReasonCode.CHANGE_ASSESSMENT,
            GovernanceReasonCode.VALIDATION_FAILED,
        }),
        expected_policy_valid=False,
        expected_validation_valid=False,
    ),
    # 23. Merge conflict
    GovernanceGoldenScenario(
        name="merge_conflict",
        expected_decision=DecisionResult.REVIEW,
        expected_bump="none",
        expected_breaking=False,
        expected_reason_codes=frozenset({
            GovernanceReasonCode.CHANGE_ASSESSMENT,
            GovernanceReasonCode.MERGE_CONFLICT,
        }),
        merge_conflicts=(
            MergeConflict(
                path="schema[orders].properties[amount]",
                message="Conflicting description updates from upstream branches",
                rule="description_conflict",
                schema_id="orders",
                property_name="amount",
            ),
        ),
        expected_policy_valid=True,
        expected_validation_valid=True,
    ),
)


def _load_contract_from_yaml(yaml_path: Path) -> OpenDataContractStandard:
    """Load an OpenDataContractStandard instance from a YAML fixture path."""
    content = yaml_path.read_text(encoding="utf-8")
    payload = yaml.safe_load(content)
    return OpenDataContractStandard.model_validate(payload)


# ==============================================================================
# Phase 4 & 5: Parameterized Golden Scenario Runner & Domain Assertions
# ==============================================================================


@pytest.mark.parametrize("scenario", SCENARIO_MATRIX, ids=lambda s: s.name)
def test_governance_golden_scenarios(scenario: GovernanceGoldenScenario) -> None:
    """Evaluate golden scenario, verify domain invariants, and compare byte-exact public JSON."""
    scenario_dir = FIXTURES_DIR / scenario.name
    assert scenario_dir.exists(), f"Scenario directory missing: {scenario_dir}"

    base_path = scenario_dir / "base.yaml"
    cand_path = scenario_dir / "candidate.yaml"
    expected_path = scenario_dir / "expected.json"

    assert base_path.exists(), f"base.yaml missing for {scenario.name}"
    assert cand_path.exists(), f"candidate.yaml missing for {scenario.name}"
    assert expected_path.exists(), f"expected.json missing for {scenario.name}"

    base_contract = _load_contract_from_yaml(base_path)
    cand_contract = _load_contract_from_yaml(cand_path)

    # 1. Evaluate internal governance decision
    decision = evaluate_governance_decision(
        base_contract,
        cand_contract,
        context=TEST_CONTEXT,
        merge_conflicts=scenario.merge_conflicts,
    )

    # 2. Direct domain-level assertions (Phase 5)
    assert decision.decision == scenario.expected_decision, (
        f"[{scenario.name}] decision mismatch: got {decision.decision}, expected {scenario.expected_decision}"
    )
    assert decision.breaking == scenario.expected_breaking, (
        f"[{scenario.name}] breaking flag mismatch: got {decision.breaking}, expected {scenario.expected_breaking}"
    )
    assert decision.required_version_bump == scenario.expected_bump, (
        f"[{scenario.name}] required_version_bump mismatch: got {decision.required_version_bump}, expected {scenario.expected_bump}"
    )

    actual_reason_codes = frozenset(r.code for r in decision.reasons)
    assert actual_reason_codes == scenario.expected_reason_codes, (
        f"[{scenario.name}] reason codes mismatch: "
        f"expected {scenario.expected_reason_codes}, got {actual_reason_codes}"
    )

    if scenario.expected_policy_valid is not None:
        assert decision.policy.valid == scenario.expected_policy_valid, (
            f"[{scenario.name}] policy.valid mismatch: got {decision.policy.valid}, expected {scenario.expected_policy_valid}"
        )

    if scenario.expected_validation_valid is not None:
        assert decision.validation.valid == scenario.expected_validation_valid, (
            f"[{scenario.name}] validation.valid mismatch: got {decision.validation.valid}, expected {scenario.expected_validation_valid}"
        )

    # 3. Public projection and read-only byte-exact golden comparison (Phase 3 & 4)
    public_decision = to_public_governance_decision(decision)
    actual_json = serialize_public_governance_decision(public_decision, indent=2) + "\n"
    expected_json = expected_path.read_text(encoding="utf-8")

    assert actual_json == expected_json, (
        f"[{scenario.name}] Golden JSON mismatch:\n"
        f"--- Actual ---\n{actual_json}\n"
        f"--- Expected ---\n{expected_json}"
    )


# ==============================================================================
# Phase 6: Lifecycle Regression Coverage
# ==============================================================================


def test_lifecycle_draft_entity_skips_breaking_checks() -> None:
    """Modifying/tightening a property marked as draft in active contract skips breaking checks."""
    scenario_dir = FIXTURES_DIR / "draft_entity_change"
    base = _load_contract_from_yaml(scenario_dir / "base.yaml")
    cand = _load_contract_from_yaml(scenario_dir / "candidate.yaml")

    decision = evaluate_governance_decision(base, cand, context=TEST_CONTEXT)

    assert decision.decision == DecisionResult.REVIEW
    assert decision.breaking is False
    assert decision.required_version_bump == "minor"
    assert len(decision.policy.breaking_changes) == 0


def test_lifecycle_deprecated_entity_skips_breaking_checks() -> None:
    """Modifying/tightening a property marked as deprecated in active contract skips breaking checks."""
    scenario_dir = FIXTURES_DIR / "deprecated_entity_change"
    base = _load_contract_from_yaml(scenario_dir / "base.yaml")
    cand = _load_contract_from_yaml(scenario_dir / "candidate.yaml")

    decision = evaluate_governance_decision(base, cand, context=TEST_CONTEXT)

    assert decision.decision == DecisionResult.REVIEW
    assert decision.breaking is False
    assert decision.required_version_bump == "minor"
    assert len(decision.policy.breaking_changes) == 0


def test_lifecycle_active_to_retired_transition_reviewable() -> None:
    """Active contract transitioning to retired is reviewable (not blocked)."""
    scenario_dir = FIXTURES_DIR / "active_to_retired_transition"
    base = _load_contract_from_yaml(scenario_dir / "base.yaml")
    cand = _load_contract_from_yaml(scenario_dir / "candidate.yaml")

    decision = evaluate_governance_decision(base, cand, context=TEST_CONTEXT)

    assert decision.decision == DecisionResult.REVIEW
    assert decision.policy.retired_violation is False
    assert any(
        r.code == GovernanceReasonCode.CONTRACT_RETIRED_TRANSITION
        for r in decision.reasons
    )


def test_lifecycle_retired_contract_mutation_blocked() -> None:
    """Mutating an already retired contract is strictly blocked with RETIRED_CONTRACT_MODIFIED."""
    scenario_dir = FIXTURES_DIR / "retired_contract_mutation"
    base = _load_contract_from_yaml(scenario_dir / "base.yaml")
    cand = _load_contract_from_yaml(scenario_dir / "candidate.yaml")

    decision = evaluate_governance_decision(base, cand, context=TEST_CONTEXT)

    assert decision.decision == DecisionResult.BLOCK
    assert decision.policy.retired_violation is True
    assert any(
        r.code == GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED
        for r in decision.reasons
    )


# ==============================================================================
# Phase 7: Canonical Identity Stability
# ==============================================================================


def test_physical_name_identity_stability() -> None:
    """Changing physicalName does not alter canonical GovernanceChange.identity."""
    scenario_dir = FIXTURES_DIR / "physical_name_identity_stability"
    base = _load_contract_from_yaml(scenario_dir / "base.yaml")
    cand = _load_contract_from_yaml(scenario_dir / "candidate.yaml")

    decision = evaluate_governance_decision(base, cand, context=TEST_CONTEXT)

    assert decision.decision == DecisionResult.REVIEW
    assert decision.breaking is False

    schema_changes = [c for c in decision.changes if c.entity_type.value == "SCHEMA"]
    property_changes = [c for c in decision.changes if c.entity_type.value == "PROPERTY"]

    # Canonical identity must remain lowercase schema and property names
    assert schema_changes
    assert property_changes
    assert {c.identity for c in schema_changes} == {("orders",)}
    assert {c.identity for c in property_changes} == {("orders", "id")}


# ==============================================================================
# Phase 8: Reason-Code Coverage Invariant
# ==============================================================================


def test_all_producible_p0_reason_codes_covered() -> None:
    """Verify that all producible P0 reason codes have regression scenario coverage."""
    covered_codes: set[GovernanceReasonCode] = set()
    for scenario in SCENARIO_MATRIX:
        covered_codes.update(scenario.expected_reason_codes)

    # Registered reason codes in semapact
    all_codes = set(GovernanceReasonCode)

    # ENUM_VALUES_REMOVED cannot be produced from ODCS YAML because upstream
    # open_data_contract_standard Pydantic model drops 'enum' on SchemaProperty.
    deferred_codes = {GovernanceReasonCode.ENUM_VALUES_REMOVED}

    producible_codes = all_codes - deferred_codes
    missing_codes = producible_codes - covered_codes

    assert not missing_codes, f"Missing regression coverage for P0 reason codes: {missing_codes}"


# ==============================================================================
# Phase 9: Determinism Tests
# ==============================================================================


def test_repeated_evaluation_determinism() -> None:
    """Repeated evaluation on identical inputs produces identical decision_id and byte-exact JSON."""
    scenario_dir = FIXTURES_DIR / "decimal_precision_reduction"
    base = _load_contract_from_yaml(scenario_dir / "base.yaml")
    cand = _load_contract_from_yaml(scenario_dir / "candidate.yaml")

    first_dec = evaluate_governance_decision(base, cand, context=TEST_CONTEXT)
    first_json = serialize_public_governance_decision(
        to_public_governance_decision(first_dec), indent=2
    )

    for _ in range(10):
        subsequent_dec = evaluate_governance_decision(base, cand, context=TEST_CONTEXT)
        subsequent_json = serialize_public_governance_decision(
            to_public_governance_decision(subsequent_dec), indent=2
        )

        assert subsequent_dec.decision_id == first_dec.decision_id
        assert subsequent_dec.decision == first_dec.decision
        assert subsequent_json == first_json
        assert subsequent_json.encode("utf-8") == first_json.encode("utf-8")


def test_non_semantic_key_ordering_determinism() -> None:
    """Differing key insertion orders in contract dictionaries yield identical fingerprints and decision_ids."""
    base_dict_1 = {
        "apiVersion": "v3.1.0",
        "kind": "DataContract",
        "id": "orders-contract",
        "name": "orders-contract",
        "version": "1.0.0",
        "status": "active",
        "schema": [
            {
                "id": "orders",
                "name": "orders",
                "properties": [
                    {
                        "id": "id",
                        "name": "id",
                        "logicalType": "string",
                        "physicalType": "varchar(64)",
                        "required": True,
                    }
                ],
            }
        ],
    }

    # Same content, different key insertion order
    base_dict_2 = {
        "status": "active",
        "version": "1.0.0",
        "name": "orders-contract",
        "id": "orders-contract",
        "kind": "DataContract",
        "apiVersion": "v3.1.0",
        "schema": [
            {
                "properties": [
                    {
                        "required": True,
                        "physicalType": "varchar(64)",
                        "logicalType": "string",
                        "name": "id",
                        "id": "id",
                    }
                ],
                "name": "orders",
                "id": "orders",
            }
        ],
    }

    base_1 = OpenDataContractStandard.model_validate(base_dict_1)
    base_2 = OpenDataContractStandard.model_validate(base_dict_2)

    dec_1 = evaluate_governance_decision(base_1, base_1, context=TEST_CONTEXT)
    dec_2 = evaluate_governance_decision(base_2, base_2, context=TEST_CONTEXT)

    assert dec_1.decision_id == dec_2.decision_id
    assert to_public_governance_decision(dec_1).to_canonical_json(
        indent=2
    ) == to_public_governance_decision(dec_2).to_canonical_json(indent=2)


def test_merge_conflict_ordering_determinism() -> None:
    """Merge conflicts provided in different input orders are canonically sorted and produce identical decision_id."""
    base = _load_contract_from_yaml(FIXTURES_DIR / "no_change" / "base.yaml")

    c1 = MergeConflict(
        path="schema[orders].properties[id]",
        message="Conflict A",
        rule="rule_a",
        schema_id="orders",
        property_name="id",
    )
    c2 = MergeConflict(
        path="schema[orders].properties[amount]",
        message="Conflict B",
        rule="rule_b",
        schema_id="orders",
        property_name="amount",
    )

    dec_forward = evaluate_governance_decision(
        base, base, context=TEST_CONTEXT, merge_conflicts=(c1, c2)
    )
    dec_reverse = evaluate_governance_decision(
        base, base, context=TEST_CONTEXT, merge_conflicts=(c2, c1)
    )

    assert dec_forward.decision_id == dec_reverse.decision_id
    assert dec_forward.reasons == dec_reverse.reasons
    assert to_public_governance_decision(dec_forward).to_canonical_json(
        indent=2
    ) == to_public_governance_decision(dec_reverse).to_canonical_json(indent=2)


# ==============================================================================
# Read-Only Verification
# ==============================================================================


def test_fixtures_are_read_only() -> None:
    """Confirm fixtures directory contents are strictly unchanged after running test suite."""
    hashes_before: dict[str, str] = {}
    for f in FIXTURES_DIR.rglob("*"):
        if f.is_file():
            hashes_before[str(f.relative_to(FIXTURES_DIR))] = hashlib.sha256(
                f.read_bytes()
            ).hexdigest()

    # Re-run all scenarios in memory
    for scenario in SCENARIO_MATRIX:
        s_dir = FIXTURES_DIR / scenario.name
        b = _load_contract_from_yaml(s_dir / "base.yaml")
        c = _load_contract_from_yaml(s_dir / "candidate.yaml")
        d = evaluate_governance_decision(
            b, c, context=TEST_CONTEXT, merge_conflicts=scenario.merge_conflicts
        )
        pub = to_public_governance_decision(d)
        actual = serialize_public_governance_decision(pub, indent=2) + "\n"
        expected = (s_dir / "expected.json").read_text(encoding="utf-8")
        assert actual == expected

    hashes_after: dict[str, str] = {}
    for f in FIXTURES_DIR.rglob("*"):
        if f.is_file():
            hashes_after[str(f.relative_to(FIXTURES_DIR))] = hashlib.sha256(
                f.read_bytes()
            ).hexdigest()

    assert hashes_before == hashes_after
