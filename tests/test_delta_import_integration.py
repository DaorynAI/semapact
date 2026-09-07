from __future__ import annotations

from pathlib import Path

import pyarrow as pa
from deltalake import write_deltalake
from open_data_contract_standard.model import CustomProperty, SchemaProperty

from semapact.governance.models import DecisionResult
from semapact.importers.delta_importer import (
    DeltaTableImporter,
    _extract_delta_relationships,
)
from semapact.interfaces.commands.utils import _split_discovered_delta_tables
from semapact.services import GovernanceService
from semapact.utils.storage_adapter import LocalStorageAdapter


def _write_table(path: Path, *, ids: list[int], values: list[str]) -> None:
    write_deltalake(
        str(path),
        pa.table({"id": ids, "value": values}),
        mode="overwrite",
    )


def _lifecycle(value: str) -> CustomProperty:
    return CustomProperty(property="lifecycleStatus", value=value)


def _custom_property_value(entity: object, key: str) -> str | None:
    for item in getattr(entity, "customProperties", None) or []:
        if str(item.property or "").strip().lower() == key.lower():
            return str(item.value)
    return None


def test_extract_delta_relationships_ignores_unrelated_configuration() -> None:
    metadata = {
        "configuration": {
            "delta.appendOnly": "false",
            "description": "Orders table",
            "semapact.fk.customer_id": "customers.id",
        }
    }

    relationships = _extract_delta_relationships(metadata)

    assert relationships is not None
    assert set(relationships) == {"customer_id"}
    assert [relationship.to for relationship in relationships["customer_id"]] == [
        "customers.id"
    ]


def test_extract_delta_relationships_returns_none_without_fk_configuration() -> None:
    metadata = {
        "configuration": {
            "delta.appendOnly": "false",
            "delta.enableChangeDataFeed": "true",
        }
    }

    assert _extract_delta_relationships(metadata) is None


def test_local_delta_discovery_and_import_end_to_end(tmp_path: Path) -> None:
    orders = tmp_path / "orders"
    payments = tmp_path / "payments"
    not_delta = tmp_path / "notes"

    _write_table(orders, ids=[1, 2], values=["a", "b"])
    _write_table(payments, ids=[10, 11], values=["x", "y"])
    not_delta.mkdir()

    discovered = LocalStorageAdapter().discover_delta_tables(str(tmp_path))
    primary, additional = _split_discovered_delta_tables(str(tmp_path), discovered)

    contract = DeltaTableImporter("delta").import_source(
        primary,
        {"table_uris": additional},
    )

    assert len(discovered) == 2
    assert str(not_delta.absolute()) not in discovered
    assert primary != str(tmp_path)
    assert {primary, *additional} == {
        str(orders.absolute()),
        str(payments.absolute()),
    }

    schemas = contract.schema_ or []
    assert {schema.name for schema in schemas} == {"orders", "payments"}
    assert len(schemas) == 2
    for schema in schemas:
        assert {prop.name for prop in (schema.properties or [])} == {"id", "value"}


def test_local_delta_import_preserves_governance_regression_path(tmp_path: Path) -> None:
    orders = tmp_path / "orders"
    _write_table(orders, ids=[1, 2], values=["a", "b"])

    source = DeltaTableImporter("delta").import_source(str(orders), {})
    governed = source.model_copy(deep=True)
    governed.status = "active"

    for schema in governed.schema_ or []:
        schema.customProperties = [
            *(schema.customProperties or []),
            _lifecycle("active"),
        ]
        for prop in schema.properties or []:
            prop.customProperties = [
                *(prop.customProperties or []),
                _lifecycle("active"),
            ]

    orders_schema = next(
        schema for schema in governed.schema_ or [] if schema.name == "orders"
    )
    orders_schema.properties = [
        *(orders_schema.properties or []),
        SchemaProperty(
            id="legacy-col",
            name="legacy_col",
            physicalName="legacy_col",
            logicalType="string",
            physicalType="string",
            required=False,
            customProperties=[_lifecycle("active")],
        ),
    ]

    analysis = GovernanceService().merge_and_evaluate(
        source,
        governed,
        effective_date="2026-09-07",
    )

    merged_orders = next(
        schema
        for schema in analysis.merge_result.contract.schema_ or []
        if schema.name == "orders"
    )
    legacy = next(
        prop for prop in merged_orders.properties or [] if prop.name == "legacy_col"
    )

    assert analysis.decision.context == analysis.context
    assert analysis.decision.decision == DecisionResult.REVIEW
    assert analysis.decision.required_version_bump == "minor"
    assert _custom_property_value(legacy, "lifecycleStatus") == "deprecated"
    assert _custom_property_value(legacy, "deprecationDate") == "2026-09-07"
