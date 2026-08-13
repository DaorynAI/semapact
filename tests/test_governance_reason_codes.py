"""Regression tests for stable, machine-readable governance reason codes."""

from __future__ import annotations

from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.governance import (
    GOVERNANCE_REASON_REGISTRY,
    GovernanceReasonCode,
    GovernanceSeverity,
    evaluate_governance_decision,
)
from semapact.lifecycle.policy import evaluate_merge_policy


ISSUE_78_PUBLIC_CODES = {
    GovernanceReasonCode.CONTRACT_ID_CHANGED,
    GovernanceReasonCode.CONTRACT_VERSION_MANUALLY_CHANGED,
    GovernanceReasonCode.SCHEMA_REMOVED,
    GovernanceReasonCode.PROPERTY_REMOVED,
    GovernanceReasonCode.RELATIONSHIP_REMOVED,
    GovernanceReasonCode.LOGICAL_TYPE_CHANGED,
    GovernanceReasonCode.PHYSICAL_TYPE_NARROWED,
    GovernanceReasonCode.DECIMAL_PRECISION_REDUCED,
    GovernanceReasonCode.DECIMAL_SCALE_REDUCED,
    GovernanceReasonCode.REQUIRED_TIGHTENED,
    GovernanceReasonCode.ENUM_VALUES_REMOVED,
    GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED,
    GovernanceReasonCode.VALIDATION_FAILED,
    GovernanceReasonCode.MERGE_CONFLICT,
}


def _contract(
    *,
    contract_id: str = "orders-contract",
    version: str = "1.0.0",
    status: str = "active",
    properties: list[SchemaProperty] | None = None,
) -> OpenDataContractStandard:
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
                properties=properties
                or [
                    SchemaProperty(
                        name="amount",
                        logicalType="number",
                        physicalType="decimal(10,2)",
                        required=False,
                    )
                ],
            )
        ],
    )


def _codes(base: OpenDataContractStandard, candidate: OpenDataContractStandard) -> set[GovernanceReasonCode]:
    return {item.code for item in evaluate_merge_policy(base, candidate).breaking_changes}


def test_issue_78_public_codes_are_registered_once_with_semantics():
    assert ISSUE_78_PUBLIC_CODES.issubset(GOVERNANCE_REASON_REGISTRY)
    assert len({code.value for code in GovernanceReasonCode}) == len(GovernanceReasonCode)
    for code in ISSUE_78_PUBLIC_CODES:
        definition = GOVERNANCE_REASON_REGISTRY[code]
        assert definition.description
        assert definition.severity in GovernanceSeverity


def test_root_identity_and_version_conditions_have_exact_codes():
    base = _contract(status="draft")

    id_changed = _contract(contract_id="different-contract", status="draft")
    assert _codes(base, id_changed) == {GovernanceReasonCode.CONTRACT_ID_CHANGED}

    version_changed = _contract(version="2.0.0", status="draft")
    assert _codes(base, version_changed) == {
        GovernanceReasonCode.CONTRACT_VERSION_MANUALLY_CHANGED
    }


def test_schema_and_property_removal_have_exact_codes():
    base = _contract()

    schema_removed = _contract()
    schema_removed.schema_ = []
    assert GovernanceReasonCode.SCHEMA_REMOVED in _codes(base, schema_removed)

    property_removed = _contract()
    property_removed.schema_[0].properties = []
    assert GovernanceReasonCode.PROPERTY_REMOVED in _codes(base, property_removed)


def test_property_breaking_conditions_have_distinct_exact_codes():
    base = _contract()

    logical_changed = _contract(
        properties=[
            SchemaProperty(
                name="amount",
                logicalType="string",
                physicalType="decimal(10,2)",
                required=False,
            )
        ]
    )
    assert GovernanceReasonCode.LOGICAL_TYPE_CHANGED in _codes(base, logical_changed)

    physical_narrowed_base = _contract(
        properties=[
            SchemaProperty(
                name="amount",
                logicalType="string",
                physicalType="varchar(100)",
                required=False,
            )
        ]
    )
    physical_narrowed = _contract(
        properties=[
            SchemaProperty(
                name="amount",
                logicalType="string",
                physicalType="varchar(20)",
                required=False,
            )
        ]
    )
    assert GovernanceReasonCode.PHYSICAL_TYPE_NARROWED in _codes(
        physical_narrowed_base, physical_narrowed
    )

    precision_reduced = _contract(
        properties=[
            SchemaProperty(
                name="amount",
                logicalType="number",
                physicalType="decimal(8,2)",
                required=False,
            )
        ]
    )
    precision_codes = _codes(base, precision_reduced)
    assert GovernanceReasonCode.DECIMAL_PRECISION_REDUCED in precision_codes
    assert GovernanceReasonCode.DECIMAL_SCALE_REDUCED not in precision_codes

    scale_reduced = _contract(
        properties=[
            SchemaProperty(
                name="amount",
                logicalType="number",
                physicalType="decimal(10,1)",
                required=False,
            )
        ]
    )
    scale_codes = _codes(base, scale_reduced)
    assert GovernanceReasonCode.DECIMAL_SCALE_REDUCED in scale_codes
    assert GovernanceReasonCode.DECIMAL_PRECISION_REDUCED not in scale_codes

    required_tightened = _contract(
        properties=[
            SchemaProperty(
                name="amount",
                logicalType="number",
                physicalType="decimal(10,2)",
                required=True,
            )
        ]
    )
    assert GovernanceReasonCode.REQUIRED_TIGHTENED in _codes(base, required_tightened)


def test_reason_code_serialization_is_stable_and_message_is_descriptive_only():
    base = _contract()
    candidate = _contract()
    candidate.schema_[0].properties = []

    first = evaluate_governance_decision(base, candidate)
    second = evaluate_governance_decision(base, candidate)

    first_json = first.model_dump(mode="json")
    second_json = second.model_dump(mode="json")
    assert first_json == second_json
    assert first.decision_id == second.decision_id

    removed = next(
        reason
        for reason in first_json["reasons"]
        if reason["code"] == GovernanceReasonCode.PROPERTY_REMOVED.value
    )
    assert removed["path"] == "schema[orders].properties[amount]"
    assert removed["severity"] == GovernanceSeverity.WARNING.value
    assert isinstance(removed["message"], str)
    assert removed["details"] == {}
