"""Unit tests for canonical ODCS-aware GovernanceChange analyzer and models."""

from __future__ import annotations

from typing import Any
from open_data_contract_standard.model import (
    CustomProperty,
    DataQuality,
    OpenDataContractStandard,
    Relationship,
    SchemaObject,
    SchemaProperty,
)

from semapact.lifecycle.changes import (
    GovernanceChange,
    GovernanceChangeDomain,
    GovernanceChangeType,
    GovernanceEntityType,
    analyze_governance_changes,
    describe_governance_change,
    governance_change_sort_key,
)


def _make_base_contract(**kwargs: Any) -> OpenDataContractStandard:
    payload: dict[str, Any] = {
        "apiVersion": "v3.1.0",
        "kind": "DataContract",
        "id": "urn:datacontract:orders",
        "name": "orders_contract",
        "version": "1.0.0",
        "status": "active",
        "description": {"usage": "Base orders contract"},
        "tags": ["orders", "finance"],
        "schema": [
            {
                "name": "orders",
                "physicalName": "tbl_orders",
                "properties": [
                    {
                        "name": "order_id",
                        "logicalType": "string",
                        "physicalType": "varchar(32)",
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
# 1. Core Analyzer Matrix
# ==============================================================================


class TestGovernanceChangeAnalyzer:
    """Test core change analyzer across all ODCS entities and change types."""

    def test_identical_contracts_produce_empty_changes(self) -> None:
        base = _make_base_contract()
        cand = _make_base_contract()
        changes = analyze_governance_changes(base, cand)
        assert changes == ()

    def test_schema_addition_produces_add_schema(self) -> None:
        base = _make_base_contract()
        cand = _make_base_contract()
        assert cand.schema_ is not None
        cand.schema_.append(
            SchemaObject(
                name="customers",
                physicalName="tbl_customers",
                properties=[
                    SchemaProperty(name="customer_id", logicalType="string", required=True)
                ],
            )
        )

        changes = analyze_governance_changes(base, cand)
        schema_adds = [
            c for c in changes
            if c.change_type == GovernanceChangeType.ADD and c.entity_type == GovernanceEntityType.SCHEMA
        ]
        assert len(schema_adds) == 1
        assert schema_adds[0].identity == ("customers",)
        assert schema_adds[0].path == "schema[customers]"
        assert schema_adds[0].domain == GovernanceChangeDomain.STRUCTURE
        assert schema_adds[0].before is None
        assert schema_adds[0].after is not None

    def test_schema_removal_produces_remove_schema(self) -> None:
        base = _make_base_contract()
        cand = _make_base_contract()
        cand.schema_ = []

        changes = analyze_governance_changes(base, cand)
        schema_removes = [
            c for c in changes
            if c.change_type == GovernanceChangeType.REMOVE and c.entity_type == GovernanceEntityType.SCHEMA
        ]
        assert len(schema_removes) == 1
        assert schema_removes[0].identity == ("orders",)
        assert schema_removes[0].path == "schema[orders]"
        assert schema_removes[0].domain == GovernanceChangeDomain.STRUCTURE
        assert schema_removes[0].before is not None
        assert schema_removes[0].after is None

    def test_property_addition_produces_add_property(self) -> None:
        base = _make_base_contract()
        cand = _make_base_contract()
        assert cand.schema_ is not None and cand.schema_[0].properties is not None
        cand.schema_[0].properties.append(
            SchemaProperty(name="currency", logicalType="string", physicalType="varchar(3)")
        )

        changes = analyze_governance_changes(base, cand)
        prop_adds = [
            c for c in changes
            if c.change_type == GovernanceChangeType.ADD and c.entity_type == GovernanceEntityType.PROPERTY
        ]
        assert len(prop_adds) == 1
        assert prop_adds[0].identity == ("orders", "currency")
        assert prop_adds[0].path == "schema[orders].properties[currency]"
        assert prop_adds[0].domain == GovernanceChangeDomain.STRUCTURE

    def test_property_removal_produces_remove_property(self) -> None:
        base = _make_base_contract()
        cand = _make_base_contract()
        assert cand.schema_ is not None and cand.schema_[0].properties is not None
        # Remove amount property
        cand.schema_[0].properties = [cand.schema_[0].properties[0]]

        changes = analyze_governance_changes(base, cand)
        prop_removes = [
            c for c in changes
            if c.change_type == GovernanceChangeType.REMOVE and c.entity_type == GovernanceEntityType.PROPERTY
        ]
        assert len(prop_removes) == 1
        assert prop_removes[0].identity == ("orders", "amount")
        assert prop_removes[0].path == "schema[orders].properties[amount]"
        assert prop_removes[0].domain == GovernanceChangeDomain.STRUCTURE

    def test_property_field_modifications(self) -> None:
        base = _make_base_contract()
        cand = _make_base_contract()
        assert cand.schema_ is not None and cand.schema_[0].properties is not None
        # Modify amount logicalType, physicalType, and required
        cand.schema_[0].properties[1].logicalType = "integer"
        cand.schema_[0].properties[1].physicalType = "bigint"
        cand.schema_[0].properties[1].required = True

        changes = analyze_governance_changes(base, cand)
        field_map = {c.field: c for c in changes if c.entity_type == GovernanceEntityType.PROPERTY}

        assert "logicalType" in field_map
        assert field_map["logicalType"].change_type == GovernanceChangeType.MODIFY
        assert field_map["logicalType"].before == "number"
        assert field_map["logicalType"].after == "integer"
        assert field_map["logicalType"].domain == GovernanceChangeDomain.STRUCTURE

        assert "physicalType" in field_map
        assert field_map["physicalType"].change_type == GovernanceChangeType.MODIFY
        assert field_map["physicalType"].before == "decimal(10,2)"
        assert field_map["physicalType"].after == "bigint"
        assert field_map["physicalType"].domain == GovernanceChangeDomain.STRUCTURE

        assert "required" in field_map
        assert field_map["required"].change_type == GovernanceChangeType.MODIFY
        assert field_map["required"].before is False
        assert field_map["required"].after is True
        assert field_map["required"].domain == GovernanceChangeDomain.STRUCTURE

    def test_property_deprecation_coalesces_companion_metadata(self) -> None:
        base = _make_base_contract()
        assert base.schema_ is not None and base.schema_[0].properties is not None
        base.schema_[0].properties[1].tags = ["orders"]

        cand = _make_base_contract()
        assert cand.schema_ is not None and cand.schema_[0].properties is not None
        cand.schema_[0].properties[1].tags = ["orders"]
        # Auto-deprecation simulates setting lifecycleStatus, deprecationDate, semapact.removed, and tag
        cand.schema_[0].properties[1].customProperties = [
            CustomProperty(property="lifecycleStatus", value="deprecated"),
            CustomProperty(property="deprecationDate", value="2026-08-15"),
            CustomProperty(property="semapact.removed", value="true"),
        ]
        cand.schema_[0].properties[1].tags = ["orders", "deprecated"]

        changes = analyze_governance_changes(base, cand)
        dep_changes = [
            c for c in changes
            if c.change_type == GovernanceChangeType.DEPRECATE and c.entity_type == GovernanceEntityType.PROPERTY
        ]
        assert len(dep_changes) == 1
        assert dep_changes[0].identity == ("orders", "amount")
        assert dep_changes[0].field == "lifecycleStatus"
        assert dep_changes[0].after == "deprecated"
        assert dep_changes[0].domain == GovernanceChangeDomain.LIFECYCLE

        # Companion metadata changes must NOT be emitted as separate changes
        companion_changes = [
            c for c in changes
            if c.field in ("customProperties.deprecationDate", "customProperties.semapact.removed", "tags")
        ]
        assert len(companion_changes) == 0

    def test_nested_property_ancestry_identity(self) -> None:
        base = _make_base_contract()
        assert base.schema_ is not None and base.schema_[0].properties is not None
        base.schema_[0].properties.append(
            SchemaProperty(
                name="customer",
                logicalType="object",
                properties=[
                    SchemaProperty(
                        name="address",
                        logicalType="object",
                        properties=[
                            SchemaProperty(name="postcode", logicalType="string", physicalType="varchar(10)")
                        ],
                    )
                ],
            )
        )

        cand = base.model_copy(deep=True)
        assert cand.schema_ is not None and cand.schema_[0].properties is not None
        # Mutate postcode physicalType
        cand.schema_[0].properties[2].properties[0].properties[0].physicalType = "varchar(5)"  # type: ignore[index]

        changes = analyze_governance_changes(base, cand)
        nested_mod = [c for c in changes if c.field == "physicalType"]
        assert len(nested_mod) == 1
        assert nested_mod[0].identity == ("orders", "customer", "address", "postcode")
        assert nested_mod[0].before == "varchar(10)"
        assert nested_mod[0].after == "varchar(5)"

    def test_relationship_add_and_remove(self) -> None:
        base = _make_base_contract()
        assert base.schema_ is not None
        base.schema_[0].relationships = [
            Relationship(type="foreignKey", to="customers.id")
        ]

        cand = _make_base_contract()
        assert cand.schema_ is not None
        cand.schema_[0].relationships = [
            Relationship(type="foreignKey", to="products.sku")
        ]

        changes = analyze_governance_changes(base, cand)
        rel_changes = [c for c in changes if c.entity_type == GovernanceEntityType.RELATIONSHIP]
        assert len(rel_changes) == 2

        removed = [c for c in rel_changes if c.change_type == GovernanceChangeType.REMOVE]
        added = [c for c in rel_changes if c.change_type == GovernanceChangeType.ADD]
        assert len(removed) == 1
        assert len(added) == 1
        assert removed[0].domain == GovernanceChangeDomain.RELATIONSHIP
        assert added[0].domain == GovernanceChangeDomain.RELATIONSHIP

    def test_same_relationship_signature_across_schemas_remove_from_one_only(self) -> None:
        """Schema A and B both have same relationship signature; removing from A emits one REMOVE pointing to A."""
        base = _make_base_contract()
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
        # Remove relationship from schema A (orders) only, keep on schema B (invoices)
        cand.schema_[0].relationships = []

        changes = analyze_governance_changes(base, cand)
        rel_removes = [
            c for c in changes
            if c.change_type == GovernanceChangeType.REMOVE and c.entity_type == GovernanceEntityType.RELATIONSHIP
        ]
        assert len(rel_removes) == 1
        assert rel_removes[0].identity[0] == "orders"
        assert rel_removes[0].path == "schema[orders].relationships"
        assert rel_removes[0].domain == GovernanceChangeDomain.RELATIONSHIP

    def test_quality_rule_add_and_remove(self) -> None:
        base = _make_base_contract()
        assert base.schema_ is not None
        base.schema_[0].quality = [
            DataQuality(type="sql", query="SELECT COUNT(*) FROM tbl_orders", name="row_count")
        ]

        cand = _make_base_contract()
        assert cand.schema_ is not None
        cand.schema_[0].quality = [
            DataQuality(type="sql", query="SELECT COUNT(*) FROM tbl_orders WHERE amount > 0", name="positive_amounts")
        ]

        changes = analyze_governance_changes(base, cand)
        qual_changes = [c for c in changes if c.entity_type == GovernanceEntityType.QUALITY]
        assert len(qual_changes) == 2
        removed = [c for c in qual_changes if c.change_type == GovernanceChangeType.REMOVE]
        added = [c for c in qual_changes if c.change_type == GovernanceChangeType.ADD]
        assert len(removed) == 1
        assert len(added) == 1
        assert removed[0].domain == GovernanceChangeDomain.QUALITY
        assert added[0].domain == GovernanceChangeDomain.QUALITY


# ==============================================================================
# 2. Determinism and Serialization Matrix
# ==============================================================================


class TestGovernanceChangeDeterminism:
    """Test deterministic ordering, human explanation, and serialization roundtrips."""

    def test_deterministic_sort_order(self) -> None:
        base = _make_base_contract()
        cand = _make_base_contract()
        assert cand.schema_ is not None and cand.schema_[0].properties is not None
        cand.schema_[0].properties[0].physicalType = "varchar(128)"
        cand.schema_[0].properties[1].required = True
        cand.schema_[0].properties.append(
            SchemaProperty(name="z_field", logicalType="string")
        )
        cand.schema_[0].properties.insert(
            0, SchemaProperty(name="a_field", logicalType="string")
        )

        changes1 = analyze_governance_changes(base, cand)
        changes2 = analyze_governance_changes(base, cand)

        assert changes1 == changes2
        assert changes1 == tuple(sorted(changes1, key=governance_change_sort_key))

    def test_serialization_roundtrip(self) -> None:
        base = _make_base_contract()
        cand = _make_base_contract()
        assert cand.schema_ is not None and cand.schema_[0].properties is not None
        cand.schema_[0].properties[0].physicalType = "varchar(64)"
        cand.schema_[0].properties[1].required = True

        changes = analyze_governance_changes(base, cand)
        dumped = [c.model_dump(mode="json") for c in changes]
        restored = tuple(GovernanceChange.model_validate(item) for item in dumped)

        assert restored == changes

    def test_describe_governance_change_human_output(self) -> None:
        change = GovernanceChange(
            change_type=GovernanceChangeType.MODIFY,
            entity_type=GovernanceEntityType.PROPERTY,
            identity=("orders", "amount"),
            path="schema[orders].properties[amount].physicalType",
            field="physicalType",
            before="decimal(10,2)",
            after="decimal(8,2)",
            domain=GovernanceChangeDomain.STRUCTURE,
        )

        description = describe_governance_change(change)
        assert "orders.amount" in description
        assert "physicalType" in description
        assert "'decimal(10,2)'" in description
        assert "'decimal(8,2)'" in description
