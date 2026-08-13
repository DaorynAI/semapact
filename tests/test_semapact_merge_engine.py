import pytest
from open_data_contract_standard.model import (
    CustomProperty,
    Description,
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
    DataQuality,
)

import semapact.lifecycle.merge_engine as merge_engine
from semapact.lifecycle.merge_engine import ContractMergeEngine


def _cp(key: str, value: str) -> CustomProperty:
    return CustomProperty(property=key, value=value)


def _active_property(
    name: str, *, physical_type: str | None = None, logical_type: str | None = None
) -> SchemaProperty:
    return SchemaProperty(
        name=name,
        physicalType=physical_type,
        logicalType=logical_type,
        customProperties=[_cp("lifecycleStatus", "active")],
    )


def test_merge_engine_preserves_business_metadata_and_flags_removed_columns():
    existing = OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        version="1.0.0",
        id="orders",
        name="orders",
        status="active",
        schema=[
            SchemaObject(
                name="orders",
                description="Business curated order table",
                customProperties=[_cp("lifecycleStatus", "active")],
                quality=[
                    DataQuality(
                        name="row_count", metric="rowCount", mustBeGreaterThan=0
                    )
                ],
                properties=[
                    SchemaProperty(
                        name="id",
                        physicalType="BIGINT",
                        logicalType="integer",
                        description="Business order id",
                        customProperties=[_cp("lifecycleStatus", "active")],
                        quality=[
                            DataQuality(
                                name="id_duplicate_count",
                                metric="duplicateValues",
                                mustBe=0,
                            )
                        ],
                    ),
                    _active_property(
                        "legacy_col", physical_type="STRING", logical_type="string"
                    ),
                ],
            )
        ],
    )

    source = OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        version="1.0.0",
        id="orders",
        name="orders",
        status="active",
        schema=[
            SchemaObject(
                name="orders",
                customProperties=[_cp("lifecycleStatus", "active")],
                properties=[
                    _active_property("id", physical_type="INT", logical_type="integer"),
                    SchemaProperty(
                        name="amount",
                        physicalType="DECIMAL(10,2)",
                        logicalType="number",
                    ),
                ],
            )
        ],
    )

    merged = (
        ContractMergeEngine()
        .merge(base_contract=source, business_contract=existing)
        .contract
    )
    merged_schema = next(
        item for item in (merged.schema_ or []) if item.name == "orders"
    )
    assert merged_schema.description == "Business curated order table"
    assert merged_schema.quality is not None and len(merged_schema.quality) == 1

    merged_id = next(
        col for col in (merged_schema.properties or []) if col.name == "id"
    )
    assert merged_id.physicalType == "INT"
    assert merged_id.description == "Business order id"
    assert merged_id.quality is not None and len(merged_id.quality) == 1

    merged_amount = next(
        col for col in (merged_schema.properties or []) if col.name == "amount"
    )
    assert merged_amount.physicalType == "DECIMAL(10,2)"

    removed_col = next(
        col for col in (merged_schema.properties or []) if col.name == "legacy_col"
    )
    removed_props = removed_col.customProperties or []
    assert any(
        item.property == "semapact.removed" and str(item.value).lower() == "true"
        for item in removed_props
    )


def test_merge_engine_internal_helpers_cover_edge_paths():
    assert (
        merge_engine._has_removed_flag(
            [{"property": "semapact.removed", "value": "TRUE"}]
        )
        is True
    )  # noqa: SLF001


def test_merge_engine_preserves_top_level_description_and_handles_added_removed_schema_objects():
    existing = OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        version="1.0.0",
        status="active",
        description=Description(usage="business desc"),
        schema=[
            SchemaObject(
                name="legacy_table",
                customProperties=[_cp("lifecycleStatus", "active")],
                properties=[],
            )
        ],
    )
    source = OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        version="1.0.0",
        status="active",
        schema=[
            SchemaObject(
                name="new_table",
                customProperties=[_cp("lifecycleStatus", "active")],
                properties=[],
            )
        ],
    )
    merged = (
        ContractMergeEngine()
        .merge(base_contract=source, business_contract=existing)
        .contract
    )
    assert (
        merged.description is not None and merged.description.usage == "business desc"
    )
    names = [s.name for s in (merged.schema_ or [])]
    assert "new_table" in names
    legacy_obj = next(s for s in (merged.schema_ or []) if s.name == "legacy_table")
    assert legacy_obj.customProperties is not None
    assert any(
        item.property == "semapact.removed" for item in legacy_obj.customProperties
    )


def test_merge_engine_preserves_governed_contract_id_and_version():
    existing = OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        version="1.2.3",
        id="550e8400-e29b-41d4-a716-446655440000",
        status="active",
        schema=[
            SchemaObject(
                name="orders",
                properties=[SchemaProperty(name="id", physicalType="INT")],
            )
        ],
    )
    source = OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        version="7",
        id="orders-imported",
        status="active",
        schema=[
            SchemaObject(
                name="orders",
                properties=[SchemaProperty(name="id", physicalType="INT")],
            )
        ],
    )

    merged = (
        ContractMergeEngine()
        .merge(base_contract=source, business_contract=existing)
        .contract
    )

    assert merged.id == "550e8400-e29b-41d4-a716-446655440000"
    assert merged.version == "1.2.3"


def test_merge_engine_skips_auto_deprecation_for_non_active_contract():
    existing = OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        version="1.0.0",
        status="draft",
        schema=[
            SchemaObject(
                name="orders",
                properties=[SchemaProperty(name="legacy_col", physicalType="STRING")],
            )
        ],
    )
    source = OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        version="1.0.0",
        status="draft",
        schema=[SchemaObject(name="orders", properties=[])],
    )

    merged = (
        ContractMergeEngine()
        .merge(base_contract=source, business_contract=existing)
        .contract
    )
    legacy_col = merged.schema_[0].properties[0]  # type: ignore[index]
    assert legacy_col.customProperties is None or not any(
        item.property == "semapact.removed" for item in legacy_col.customProperties
    )


def test_merge_engine_skips_auto_deprecation_for_draft_property():
    existing = OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        version="1.0.0",
        status="active",
        schema=[
            SchemaObject(
                name="orders",
                customProperties=[_cp("lifecycleStatus", "active")],
                properties=[
                    SchemaProperty(
                        name="legacy_col",
                        physicalType="STRING",
                        customProperties=[_cp("lifecycleStatus", "draft")],
                    )
                ],
            )
        ],
    )
    source = OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        version="1.0.0",
        status="active",
        schema=[SchemaObject(name="orders", properties=[])],
    )

    merged = (
        ContractMergeEngine()
        .merge(base_contract=source, business_contract=existing)
        .contract
    )
    legacy_col = merged.schema_[0].properties[0]  # type: ignore[index]
    assert legacy_col.customProperties is not None
    assert not any(
        item.property == "semapact.removed" for item in legacy_col.customProperties
    )


def test_merge_engine_rejects_api_version_below_3():
    existing = OpenDataContractStandard(
        apiVersion="v2.9.0",
        kind="DataContract",
        version="1.0.0",
        status="active",
        schema=[SchemaObject(name="orders", properties=[])],
    )
    source = OpenDataContractStandard(
        apiVersion="v2.9.0",
        kind="DataContract",
        version="1.0.0",
        status="active",
        schema=[SchemaObject(name="orders", properties=[])],
    )

    with pytest.raises(Exception, match="Only v3.0.0 and above are supported"):
        ContractMergeEngine().merge(base_contract=source, business_contract=existing)


def test_merge_engine_rejects_retired_contract_modification():
    existing = OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        version="1.0.0",
        status="retired",
        schema=[SchemaObject(name="orders", properties=[])],
    )
    source = OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        version="1.0.0",
        status="active",
        schema=[
            SchemaObject(
                name="orders",
                properties=[SchemaProperty(name="id", physicalType="INT")],
            )
        ],
    )

    result = ContractMergeEngine().merge(base_contract=source, business_contract=existing)
    from semapact.governance import (
        DecisionResult,
        GovernanceReasonCode,
        evaluate_governance_decision,
    )

    decision = evaluate_governance_decision(existing, result.contract, merge_conflicts=result.conflicts)
    assert decision.decision == DecisionResult.BLOCK
    assert any(
        r.code == GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED
        for r in decision.reasons
    )


def test_merge_engine_hard_overwrites_relationships(
    relationship_merge_existing_contract_model,
    relationship_merge_missing_contract_model,
    relationship_merge_new_contract_model,
):
    merged = (
        ContractMergeEngine()
        .merge(
            base_contract=relationship_merge_missing_contract_model,
            business_contract=relationship_merge_existing_contract_model,
        )
        .contract
    )

    merged_prop = merged.schema_[0].properties[0]
    assert merged_prop.relationships is None

    merged = (
        ContractMergeEngine()
        .merge(
            base_contract=relationship_merge_new_contract_model,
            business_contract=relationship_merge_existing_contract_model,
        )
        .contract
    )

    merged_prop = merged.schema_[0].properties[0]
    assert len(merged_prop.relationships) == 1
    assert getattr(merged_prop.relationships[0], "to", None) == "products.id"
