import pytest
from open_data_contract_standard.model import SchemaObject, SchemaProperty
from semapact.exceptions import ValidationError
from semapact.lifecycle.identity import (
    build_property_index,
    build_schema_index,
    normalize_identity_name,
    schema_identity,
    validate_contract_identities,
)


def test_normalize_identity_name_valid_and_invalid():
    assert normalize_identity_name("  Orders  ", "Schema") == "orders"
    assert normalize_identity_name("USER_ID", "Property") == "user_id"

    with pytest.raises(ValidationError) as exc_info:
        normalize_identity_name(None, "Schema")
    assert "Schema name is missing" in str(exc_info.value)

    with pytest.raises(ValidationError) as exc_info:
        normalize_identity_name("   ", "Property")
    assert "Property name cannot be empty or whitespace-only" in str(exc_info.value)


def test_schema_identity_ignores_physical_name():
    schema = SchemaObject(name="  Orders  ", physicalName="physical_table_name")
    assert schema_identity(schema) == "orders"


def test_build_schema_index_normalizes_and_detects_duplicates():
    schema1 = SchemaObject(name="  Orders  ")
    schema2 = SchemaObject(name="Users")
    index = build_schema_index([schema1, schema2])

    assert set(index.keys()) == {"orders", "users"}
    assert index["orders"] is schema1

    # Duplicate canonical schema name
    schema_dup = SchemaObject(name="orders")
    with pytest.raises(ValidationError) as exc_info:
        build_schema_index([schema1, schema_dup])
    assert "Duplicate canonical schema identity found: 'orders'" in str(exc_info.value)


def test_build_property_index_accepts_scope_key_and_detects_duplicates():
    p1 = SchemaProperty(name="  Order_Id  ", type="string")
    p2 = SchemaProperty(name="amount", type="number")
    index = build_property_index("orders", [p1, p2])

    assert ("orders", "order_id") in index
    assert ("orders", "amount") in index
    assert index[("orders", "order_id")] is p1

    p_dup = SchemaProperty(name="ORDER_ID", type="string")
    with pytest.raises(ValidationError) as exc_info:
        build_property_index("orders", [p1, p_dup])
    assert "Duplicate canonical property identity found: 'order_id' in schema 'orders'" in str(
        exc_info.value
    )


def test_validate_contract_identities_recursively_validates_nested_properties():
    # Valid schema with nested properties
    nested_child = SchemaProperty(name="street", type="string")
    parent_prop = SchemaProperty(name="address", type="object", properties=[nested_child])
    valid_schema = SchemaObject(name="users", properties=[parent_prop])

    # Should pass without error
    validate_contract_identities([valid_schema])

    # Invalid: duplicate child property inside struct
    dup_child = SchemaProperty(name="STREET", type="string")
    invalid_parent = SchemaProperty(name="address", type="object", properties=[nested_child, dup_child])
    invalid_schema = SchemaObject(name="users", properties=[invalid_parent])

    with pytest.raises(ValidationError) as exc_info:
        validate_contract_identities([invalid_schema])
    assert "Duplicate canonical property identity found: 'street' in schema 'address'" in str(
        exc_info.value
    )
