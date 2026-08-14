from __future__ import annotations

from datetime import date
from open_data_contract_standard.model import (
    CustomProperty,
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.change_context import ChangeContext
from semapact.governance.evaluator import evaluate_governance_decision
from semapact.governance.models import DecisionResult
from semapact.governance_codes import GovernanceReasonCode
from semapact.lifecycle.helpers import allows_breaking_changes
from semapact.lifecycle.merge_engine import ContractMergeEngine
from semapact.services.governance_service import GovernanceService

TEST_CONTEXT = ChangeContext(effective_date=date(2026, 8, 14))


def _cp(key: str, value: str) -> CustomProperty:
    return CustomProperty(property=key, value=value)


def _base_active_contract() -> OpenDataContractStandard:
    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="orders_contract",
        version="1.0.0",
        status="active",
        schema=[
            SchemaObject(
                name="orders",
                properties=[
                    SchemaProperty(
                        name="order_id",
                        logicalType="string",
                        physicalType="VARCHAR(64)",
                    ),
                    SchemaProperty(
                        name="customer",
                        logicalType="object",
                        physicalType="STRUCT",
                        properties=[
                            SchemaProperty(
                                name="address",
                                logicalType="string",
                                physicalType="VARCHAR(256)",
                            )
                        ],
                    ),
                ],
            )
        ],
    )


def test_invalid_root_lifecycle_evaluates_to_block():
    base = _base_active_contract()
    candidate = base.model_copy(deep=True)
    candidate.status = "invalid_status_xyz"

    decision = evaluate_governance_decision(base, candidate, context=TEST_CONTEXT)
    assert decision.decision == DecisionResult.BLOCK
    assert any(
        r.code == GovernanceReasonCode.VALIDATION_FAILED
        and "Invalid contract lifecycle status" in r.message
        for r in decision.reasons
    )


def test_invalid_schema_lifecycle_evaluates_to_block():
    base = _base_active_contract()
    candidate = base.model_copy(deep=True)
    candidate.schema_[0].customProperties = [
        _cp("lifecycleStatus", "unknown_schema_status")
    ]

    decision = evaluate_governance_decision(base, candidate, context=TEST_CONTEXT)
    assert decision.decision == DecisionResult.BLOCK
    assert any(
        r.code == GovernanceReasonCode.VALIDATION_FAILED
        and "Invalid schema customProperties lifecycleStatus" in r.message
        for r in decision.reasons
    )


def test_invalid_property_lifecycle_evaluates_to_block():
    base = _base_active_contract()
    candidate = base.model_copy(deep=True)
    candidate.schema_[0].properties[0].customProperties = [
        _cp("lifecycleStatus", "invalid_prop_status")
    ]

    decision = evaluate_governance_decision(base, candidate, context=TEST_CONTEXT)
    assert decision.decision == DecisionResult.BLOCK
    assert any(
        r.code == GovernanceReasonCode.VALIDATION_FAILED
        and "Invalid property customProperties lifecycleStatus" in r.message
        for r in decision.reasons
    )


def test_invalid_nested_property_lifecycle_evaluates_to_block():
    base = _base_active_contract()
    candidate = base.model_copy(deep=True)
    candidate.schema_[0].properties[1].properties[0].customProperties = [
        _cp("lifecycleStatus", "garbage_nested_status")
    ]

    decision = evaluate_governance_decision(base, candidate, context=TEST_CONTEXT)
    assert decision.decision == DecisionResult.BLOCK
    assert any(
        r.code == GovernanceReasonCode.VALIDATION_FAILED
        and "Invalid property customProperties lifecycleStatus" in r.message
        for r in decision.reasons
    )


def test_governance_service_merge_and_evaluate_does_not_leak_value_error_on_invalid_lifecycle():
    service = GovernanceService()
    source = _base_active_contract()
    source.status = None  # technical source missing status
    source.schema_[0].properties[0].customProperties = [
        _cp("lifecycleStatus", "bad_lifecycle_token")
    ]

    governed_target = _base_active_contract()

    # Must NOT raise unhandled ValueError
    analysis = service.merge_and_evaluate(
        source_contract=source,
        business_contract=governed_target,
        effective_date=date(2026, 8, 14),
    )

    assert analysis.decision.decision == DecisionResult.BLOCK
    assert any(
        r.code == GovernanceReasonCode.VALIDATION_FAILED
        for r in analysis.decision.reasons
    )


def test_merge_engine_detects_conflict_when_source_status_missing():
    """Active governed target + unannotated/draft technical source with physical type conflict."""
    engine = ContractMergeEngine()
    target = _base_active_contract()  # status: active

    # Source has no status (defaults to DRAFT canonically)
    source = OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="orders_contract",
        version="1.0.0",
        status=None,
        schema=[
            SchemaObject(
                name="orders",
                properties=[
                    SchemaProperty(
                        name="order_id",
                        logicalType="string",
                        physicalType="INT",  # Changed from VARCHAR(64) -> conflict!
                    ),
                    SchemaProperty(
                        name="customer",
                        logicalType="object",
                        physicalType="STRUCT",
                        properties=[
                            SchemaProperty(
                                name="address",
                                logicalType="string",
                                physicalType="VARCHAR(256)",
                            )
                        ],
                    ),
                ],
            )
        ],
    )

    # Note: in merge engine convention, base_contract=source, business_contract=target
    result = engine.merge(
        base_contract=source,
        business_contract=target,
        context=TEST_CONTEXT,
    )

    # Physical type conflict MUST still be detected
    assert len(result.conflicts) > 0
    assert any(c.rule == "physical_type_change" for c in result.conflicts)


def test_merge_engine_auto_deprecates_when_source_status_proposed_or_missing():
    """Active governed target + source missing an active property -> auto-deprecation must occur."""
    engine = ContractMergeEngine()
    target = _base_active_contract()  # status: active

    # Source has status="proposed" and is missing "customer" property
    source = OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="orders_contract",
        version="1.0.0",
        status="proposed",
        schema=[
            SchemaObject(
                name="orders",
                properties=[
                    SchemaProperty(
                        name="order_id",
                        logicalType="string",
                        physicalType="VARCHAR(64)",
                    )
                ],
            )
        ],
    )

    result = engine.merge(
        base_contract=source,
        business_contract=target,
        context=TEST_CONTEXT,
    )

    # The missing 'customer' property in active target must be auto-deprecated
    merged_schema = result.contract.schema_[0]
    props = {p.name: p for p in merged_schema.properties or []}
    assert "customer" in props
    customer_prop = props["customer"]
    assert customer_prop.customProperties is not None
    cp_map = {cp.property: cp.value for cp in customer_prop.customProperties}
    assert cp_map.get("lifecycleStatus") == "deprecated"
    assert cp_map.get("semapact.removed") == "true"


def test_allows_breaking_changes_compatibility_wrapper():
    active_contract = _base_active_contract()
    draft_contract = active_contract.model_copy(deep=True)
    draft_contract.status = "draft"

    assert allows_breaking_changes(active_contract) is True
    assert allows_breaking_changes(draft_contract) is False

    active_prop = SchemaProperty(
        name="col", customProperties=[_cp("lifecycleStatus", "active")]
    )
    deprecated_prop = SchemaProperty(
        name="col", customProperties=[_cp("lifecycleStatus", "deprecated")]
    )
    assert allows_breaking_changes(active_prop) is True
    assert allows_breaking_changes(deprecated_prop) is False
