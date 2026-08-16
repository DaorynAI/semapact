"""Integration tests for GovernanceChange consumption across policy, release, merge, and evaluator."""

from __future__ import annotations

from datetime import date
from typing import Any
from open_data_contract_standard.model import (
    CustomProperty,
    DataQuality,
    Description,
    OpenDataContractStandard,
    Pricing,
    Relationship,
    SchemaObject,
    SchemaProperty,
)

from semapact.change_context import ChangeContext
from semapact.core.release import classify_contract_change
from semapact.governance import DecisionResult, evaluate_governance_decision
from semapact.governance_codes import GovernanceReasonCode
from semapact.lifecycle.changes import (
    GovernanceChangeEvidenceSource,
    analyze_governance_changes,
)
from semapact.lifecycle.merge_engine import MergeConflict
from semapact.lifecycle.policy import evaluate_merge_policy


TEST_CONTEXT = ChangeContext(effective_date=date(2026, 8, 15))


def _make_active_contract(**kwargs: Any) -> OpenDataContractStandard:
    payload: dict[str, Any] = {
        "apiVersion": "v3.1.0",
        "kind": "DataContract",
        "id": "urn:datacontract:orders",
        "name": "orders",
        "version": "1.0.0",
        "status": "active",
        "description": {"usage": "Active orders contract"},
        "tags": ["finance"],
        "schema": [
            {
                "name": "orders",
                "physicalName": "tbl_orders",
                "properties": [
                    {
                        "name": "id",
                        "logicalType": "string",
                        "physicalType": "varchar(255)",
                        "required": True,
                    },
                    {
                        "name": "amount",
                        "logicalType": "number",
                        "physicalType": "decimal(10,2)",
                        "required": False,
                    },
                ],
            }
        ],
    }
    payload.update(kwargs)
    return OpenDataContractStandard.model_validate(payload)


# ==============================================================================
# 1. Policy Projection Tests
# ==============================================================================


class TestGovernancePolicyProjection:
    """Validate that policy evaluates and annotates canonical GovernanceChange objects."""

    def test_logical_type_changed_annotates_breaking(self) -> None:
        base = _make_active_contract()
        cand = _make_active_contract()
        assert cand.schema_ is not None and cand.schema_[0].properties is not None
        cand.schema_[0].properties[0].logicalType = "integer"

        changes = analyze_governance_changes(base, cand)
        policy_eval = evaluate_merge_policy(base, cand, changes=changes)

        assert not policy_eval.valid
        assert len(policy_eval.breaking_changes) == 1
        assert policy_eval.breaking_changes[0].code == GovernanceReasonCode.LOGICAL_TYPE_CHANGED

        # Check annotated changes
        breaking_changes = [c for c in policy_eval.annotated_changes if c.breaking]
        assert len(breaking_changes) == 1
        assert GovernanceReasonCode.LOGICAL_TYPE_CHANGED in breaking_changes[0].reason_codes

    def test_decimal_precision_and_scale_reduction_single_change_two_reasons(self) -> None:
        base = _make_active_contract()
        cand = _make_active_contract()
        assert cand.schema_ is not None and cand.schema_[0].properties is not None
        # decimal(10,2) -> decimal(8,1) reduces both precision and scale
        cand.schema_[0].properties[1].physicalType = "decimal(8,1)"

        changes = analyze_governance_changes(base, cand)
        assert len(changes) == 1
        assert changes[0].field == "physicalType"

        policy_eval = evaluate_merge_policy(base, cand, changes=changes)
        assert not policy_eval.valid
        assert len(policy_eval.breaking_changes) == 2

        # In annotated changes, it remains ONE single change with TWO reason codes
        annotated = policy_eval.annotated_changes
        assert len(annotated) == 1
        assert annotated[0].breaking is True
        assert GovernanceReasonCode.DECIMAL_PRECISION_REDUCED in annotated[0].reason_codes
        assert GovernanceReasonCode.DECIMAL_SCALE_REDUCED in annotated[0].reason_codes

    def test_property_removal_annotates_breaking(self) -> None:
        base = _make_active_contract()
        cand = _make_active_contract()
        assert cand.schema_ is not None and cand.schema_[0].properties is not None
        cand.schema_[0].properties = [cand.schema_[0].properties[0]]  # remove amount

        changes = analyze_governance_changes(base, cand)
        policy_eval = evaluate_merge_policy(base, cand, changes=changes)

        assert not policy_eval.valid
        assert len(policy_eval.breaking_changes) == 1
        assert policy_eval.breaking_changes[0].code == GovernanceReasonCode.PROPERTY_REMOVED

    def test_relationship_removed_from_one_schema_emits_breaking_policy(self) -> None:
        """Removing relationship from schema A only produces one breaking change pointing to A."""
        base = _make_active_contract()
        assert base.schema_ is not None
        base.schema_[0].relationships = [
            Relationship(type="foreignKey", to="customers.id")
        ]
        base.schema_.append(
            SchemaObject(
                name="invoices",
                physicalName="tbl_invoices",
                relationships=[
                    Relationship(type="foreignKey", to="customers.id")
                ],
                properties=[
                    SchemaProperty(name="invoice_id", logicalType="string", required=True)
                ],
            )
        )

        cand = base.model_copy(deep=True)
        assert cand.schema_ is not None
        cand.schema_[0].relationships = []

        changes = analyze_governance_changes(base, cand)
        policy_eval = evaluate_merge_policy(base, cand, changes=changes)

        assert not policy_eval.valid
        assert len(policy_eval.breaking_changes) == 1
        assert policy_eval.breaking_changes[0].code == GovernanceReasonCode.RELATIONSHIP_REMOVED
        assert policy_eval.breaking_changes[0].path == "schema[orders].relationships"


# ==============================================================================
# 2. Release Parity Tests
# ==============================================================================


class TestReleaseClassificationParity:
    """Verify release classification over canonical changes produces exact expected bump."""

    def test_no_changes_requires_none_bump(self) -> None:
        base = _make_active_contract()
        cand = _make_active_contract()
        assessment = classify_contract_change(base, cand)
        assert assessment.has_changes is False
        assert assessment.required_bump == "none"

    def test_descriptive_metadata_change_requires_none_bump(self) -> None:
        base = _make_active_contract()
        cand = _make_active_contract()
        cand.description = Description(usage="Updated documentation for orders")
        cand.tags = ["finance", "updated"]

        assessment = classify_contract_change(base, cand)
        assert assessment.has_changes is True
        assert assessment.required_bump == "none"

    def test_property_addition_requires_minor_bump(self) -> None:
        base = _make_active_contract()
        cand = _make_active_contract()
        assert cand.schema_ is not None and cand.schema_[0].properties is not None
        cand.schema_[0].properties.append(
            SchemaProperty(name="currency", logicalType="string", physicalType="varchar(3)")
        )

        assessment = classify_contract_change(base, cand)
        assert assessment.has_changes is True
        assert assessment.required_bump == "minor"

    def test_property_deprecation_requires_minor_bump(self) -> None:
        base = _make_active_contract()
        cand = _make_active_contract()
        assert cand.schema_ is not None and cand.schema_[0].properties is not None
        cand.schema_[0].properties[1].customProperties = [
            CustomProperty(property="lifecycleStatus", value="deprecated")
        ]

        assessment = classify_contract_change(base, cand)
        assert assessment.has_changes is True
        assert assessment.required_bump == "minor"

    def test_quality_rule_addition_requires_minor_bump(self) -> None:
        base = _make_active_contract()
        cand = _make_active_contract()
        assert cand.schema_ is not None
        cand.schema_[0].quality = [
            DataQuality(type="sql", query="SELECT COUNT(*) FROM tbl_orders", name="row_count")
        ]

        assessment = classify_contract_change(base, cand)
        assert assessment.has_changes is True
        assert assessment.required_bump == "minor"

    def test_breaking_change_requires_major_bump(self) -> None:
        base = _make_active_contract()
        cand = _make_active_contract()
        assert cand.schema_ is not None and cand.schema_[0].properties is not None
        cand.schema_[0].properties[0].physicalType = "varchar(10)"  # narrowed

        assessment = classify_contract_change(base, cand)
        assert assessment.has_changes is True
        assert assessment.required_bump == "major"
        assert len(assessment.breaking_changes) == 1


# ==============================================================================
# 3. Merge Conflict Evidence Correlation & Evaluator Integration
# ==============================================================================


class TestEvaluatorGovernanceChangeIntegration:
    """Validate evaluator attaches merge conflict evidence and populates GovernanceDecision.changes."""

    def test_evaluator_attaches_merge_conflict_evidence(self) -> None:
        base = _make_active_contract()
        cand = _make_active_contract()
        assert cand.schema_ is not None and cand.schema_[0].properties is not None
        cand.schema_[0].properties[0].physicalType = "bigint"

        conflicts = [
            MergeConflict(
                path="schema[orders].properties[id].physicalType",
                schema_id="orders",
                property_name="id",
                rule="physical_type_conflict",
                message="Physical type conflict during merge",
            )
        ]

        decision = evaluate_governance_decision(
            base, cand, context=TEST_CONTEXT, merge_conflicts=conflicts
        )

        assert decision.evidence.has_changes is True
        assert decision.evidence.merge_conflicts_count == 1
        assert len(decision.changes) > 0

        # Verify evidence attached to matching change
        id_phys_changes = [
            c for c in decision.changes
            if c.identity == ("orders", "id") and c.field == "physicalType"
        ]
        assert len(id_phys_changes) == 1
        assert len(id_phys_changes[0].evidence) == 1
        assert id_phys_changes[0].evidence[0].source == GovernanceChangeEvidenceSource.MERGE_CONFLICT
        assert id_phys_changes[0].evidence[0].code == "physical_type_conflict"

    def test_unmatched_merge_conflict_remains_in_reasons(self) -> None:
        base = _make_active_contract()
        cand = _make_active_contract()

        conflicts = [
            MergeConflict(
                path="unknown.path",
                rule="general_conflict",
                message="Unmatched conflict message",
            )
        ]

        decision = evaluate_governance_decision(
            base, cand, context=TEST_CONTEXT, merge_conflicts=conflicts
        )

        assert any(
            r.code == GovernanceReasonCode.MERGE_CONFLICT and "Unmatched conflict message" in r.message
            for r in decision.reasons
        )

    def test_retired_base_mutation_blocks_even_with_validation_error(self) -> None:
        """Retired mutation must emit RETIRED_CONTRACT_MODIFIED even if candidate fails validation."""
        base = _make_active_contract(status="retired")
        cand = _make_active_contract(status="retired")
        assert cand.schema_ is not None and cand.schema_[0].properties is not None
        # Introduce duplicate property identity in candidate (validation error)
        cand.schema_[0].properties.append(
            SchemaProperty(name="id", logicalType="string", physicalType="text")
        )

        decision = evaluate_governance_decision(base, cand, context=TEST_CONTEXT)

        assert decision.decision == DecisionResult.BLOCK
        assert any(
            r.code == GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED
            for r in decision.reasons
        )
        assert any(
            r.code == GovernanceReasonCode.VALIDATION_FAILED
            for r in decision.reasons
        )

    def test_retired_base_unhandled_or_metadata_mutation_blocks(self) -> None:
        """Retired base mutation in metadata or top-level field produces BLOCK and RETIRED_CONTRACT_MODIFIED."""
        base = _make_active_contract(status="retired")
        cand = _make_active_contract(status="retired")
        cand.price = Pricing(priceAmount=999.0, priceCurrency="USD")

        decision = evaluate_governance_decision(base, cand, context=TEST_CONTEXT)

        assert decision.decision == DecisionResult.BLOCK
        assert any(
            r.code == GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED
            for r in decision.reasons
        )
