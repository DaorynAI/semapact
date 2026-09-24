from __future__ import annotations

from semapact.importers.unity_relationships import (
    _constraint_items,
    _parse_constraint_record,
)


def test_constraint_items_reads_sdk_table_constraints_only() -> None:
    metadata = {
        "table_constraints": [
            {"primary_key_constraint": {"name": "pk"}},
            {"foreign_key_constraint": {"name": "fk"}},
            "not-a-mapping",
        ],
        "constraints": [{"id": "non-canonical"}],
    }

    assert _constraint_items(metadata) == [
        {"primary_key_constraint": {"name": "pk"}},
        {"foreign_key_constraint": {"name": "fk"}},
    ]


def test_parse_constraint_record_maps_sdk_foreign_key_shape() -> None:
    record = _parse_constraint_record(
        {
            "foreign_key_constraint": {
                "name": "fk_orders_customer",
                "child_columns": ["customer_id"],
                "parent_table": "main.ref.customers",
                "parent_columns": ["id"],
            }
        }
    )

    assert record is not None
    assert record.constraint_name == "fk_orders_customer"
    assert record.source_columns == ["customer_id"]
    assert record.target_table == "main.ref.customers"
    assert record.target_columns == ["id"]


def test_parse_constraint_record_ignores_incomplete_foreign_key() -> None:
    assert (
        _parse_constraint_record(
            {
                "foreign_key_constraint": {
                    "name": "fk_incomplete",
                    "child_columns": ["customer_id"],
                }
            }
        )
        is None
    )
