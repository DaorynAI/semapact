from __future__ import annotations

from semapact.constants import (
    UNITY_CONSTRAINT_NAME_KEY,
    UNITY_RELATIONSHIPS_COUNT_KEY,
    UNITY_RELATIONSHIPS_IMPORTED_KEY,
)
from semapact.importers.unity_relationships import (
    enrich_unity_contract_relationships,
)


def _custom_props_map(contract) -> dict[str, object]:  # noqa: ANN001
    return {
        item.property: item.value
        for item in (contract.customProperties or [])
        if item.property
    }


def test_unity_relationship_enrichment_imports_sdk_foreign_keys(
    sample_unity_contract_model,
):
    contract = sample_unity_contract_model.model_copy(deep=True)
    assert contract.schema_ is not None
    schema = contract.schema_[0]
    assert schema.properties is not None
    template = schema.properties[0]
    schema.properties.append(
        template.model_copy(
            update={
                "id": "parent_tenant",
                "name": "parent_tenant",
                "physicalName": "parent_tenant",
                "logicalType": "string",
                "physicalType": "STRING",
                "required": True,
            }
        )
    )
    schema.properties.append(
        template.model_copy(
            update={
                "id": "parent_code",
                "name": "parent_code",
                "physicalName": "parent_code",
                "logicalType": "string",
                "physicalType": "STRING",
                "required": True,
            }
        )
    )

    enriched = enrich_unity_contract_relationships(
        contract,
        table_fqn="main.silver.orders",
        metadata={
            "table_constraints": [
                {
                    "foreign_key_constraint": {
                        "child_columns": ["id"],
                        "parent_table": "main.ref.customers",
                        "parent_columns": ["customer_id"],
                        "name": "fk_orders_customer",
                    }
                },
                {
                    "foreign_key_constraint": {
                        "child_columns": ["parent_tenant", "parent_code"],
                        "parent_table": "main.ref.parents",
                        "parent_columns": ["tenant", "code"],
                        "name": "fk_orders_parent",
                    }
                },
            ]
        },
    )

    assert enriched.schema_ is not None
    enriched_schema = enriched.schema_[0]
    assert enriched_schema.properties is not None
    fields = {item.name: item for item in enriched_schema.properties if item.name}

    assert fields["id"].relationships is not None
    assert fields["id"].relationships[0].type == "foreignKey"
    assert fields["id"].relationships[0].to == "main.ref.customers.customer_id"
    assert fields["id"].relationships[0].customProperties is not None
    rel_props = {
        item.property: item.value
        for item in fields["id"].relationships[0].customProperties
        if item.property
    }
    assert rel_props[UNITY_CONSTRAINT_NAME_KEY] == "fk_orders_customer"

    assert enriched_schema.relationships is not None
    assert enriched_schema.relationships[0].type == "foreignKey"
    assert enriched_schema.relationships[0].from_ == ["parent_tenant", "parent_code"]
    assert enriched_schema.relationships[0].to == [
        "main.ref.parents.tenant",
        "main.ref.parents.code",
    ]

    props = _custom_props_map(enriched)
    assert props[UNITY_RELATIONSHIPS_IMPORTED_KEY] == "true"
    assert props[UNITY_RELATIONSHIPS_COUNT_KEY] == "2"


def test_unity_relationship_enrichment_ignores_non_foreign_key_constraints(
    sample_unity_contract_model,
):
    contract = sample_unity_contract_model.model_copy(deep=True)

    enriched = enrich_unity_contract_relationships(
        contract,
        table_fqn="main.silver.orders",
        metadata={
            "table_constraints": [
                {
                    "primary_key_constraint": {
                        "child_columns": ["id"],
                        "name": "pk_orders",
                    }
                }
            ]
        },
    )

    props = _custom_props_map(enriched)
    assert props[UNITY_RELATIONSHIPS_IMPORTED_KEY] == "true"
    assert props[UNITY_RELATIONSHIPS_COUNT_KEY] == "0"
