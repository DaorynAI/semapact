import builtins
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.importers.unity_lineage import enrich_unity_lineage

EVENT_TIME = datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc)


def test_enrich_unity_lineage_no_http_path():
    prop_id = SchemaProperty(id="id", name="id")
    schema_obj = SchemaObject(
        name="orders", physicalName="orders", properties=[prop_id]
    )
    contract = OpenDataContractStandard(
        apiVersion="3.1.0", id="test-contract", schema=[schema_obj]
    )

    enriched = enrich_unity_lineage(
        contract,
        table_fqn="main.sales.orders",
        workspace_url="https://adb.example",
        token="token",
        sql_http_path=None,
    )

    assert enriched.schema_[0].properties[0].transformSourceObjects is None


@patch("databricks.sql.connect")
def test_enrich_unity_lineage_success(mock_sql_connect):
    prop_id = SchemaProperty(id="id", name="id")
    prop_amount = SchemaProperty(id="amount", name="amount")
    schema_obj = SchemaObject(
        name="orders", physicalName="orders", properties=[prop_id, prop_amount]
    )
    contract = OpenDataContractStandard(
        apiVersion="3.1.0", id="test-contract", schema=[schema_obj]
    )

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_sql_connect.return_value.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    class Row:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    def execute_side_effect(query, params):
        common = dict(
            target_table_full_name="main.sales.orders",
            statement_id="stmt-1",
            event_time=EVENT_TIME,
            event_id="event-1",
            record_id="record-1",
            created_by="pipeline@example.com",
            direct_access=True,
        )
        if "system.access.column_lineage" in query:
            mock_cursor.fetchall.return_value = [
                Row(
                    source_table_full_name="main.sales.raw_orders",
                    source_column_name="raw_id",
                    target_column_name="id",
                    **common,
                ),
                Row(
                    source_table_full_name="main.sales.raw_orders",
                    source_column_name="raw_amount",
                    target_column_name="amount",
                    **common,
                ),
            ]
        elif "system.query.history" in query:
            mock_cursor.fetchall.return_value = [
                Row(
                    source_table_full_name="main.sales.raw_orders",
                    statement_text="INSERT INTO main.sales.orders SELECT raw_id as id, raw_amount as amount FROM main.sales.raw_orders",
                    statement_type="INSERT",
                    **common,
                )
            ]
        else:
            mock_cursor.fetchall.return_value = [
                Row(source_table_full_name="main.sales.raw_orders", **common)
            ]

    mock_cursor.execute.side_effect = execute_side_effect

    enriched = enrich_unity_lineage(
        contract,
        table_fqn="main.sales.orders",
        workspace_url="https://adb.example",
        token="token",
        sql_http_path="/sql/1.0/endpoints/12345",
    )

    mock_sql_connect.assert_called_once_with(
        server_hostname="adb.example",
        http_path="/sql/1.0/endpoints/12345",
        access_token="token",
    )

    fields = {item.name: item for item in enriched.schema_[0].properties if item.name}
    assert fields["id"].transformSourceObjects == ["main.sales.raw_orders.raw_id"]
    assert fields["amount"].transformSourceObjects == [
        "main.sales.raw_orders.raw_amount"
    ]

    statement = "INSERT INTO main.sales.orders SELECT raw_id as id, raw_amount as amount FROM main.sales.raw_orders"
    assert fields["id"].transformLogic == statement
    assert fields["amount"].transformLogic == statement
    assert any(
        "system.query.history" in call.args[0]
        for call in mock_cursor.execute.call_args_list
    )


@patch("databricks.sql.connect")
def test_enrich_unity_lineage_exception(mock_sql_connect):
    prop_id = SchemaProperty(id="id", name="id")
    schema_obj = SchemaObject(
        name="orders", physicalName="orders", properties=[prop_id]
    )
    contract = OpenDataContractStandard(
        apiVersion="3.1.0", id="test-contract", schema=[schema_obj]
    )

    mock_sql_connect.side_effect = Exception("Connection Failed")

    enriched = enrich_unity_lineage(
        contract,
        table_fqn="main.sales.orders",
        workspace_url="https://adb.example",
        token="token",
        sql_http_path="/sql/1.0/endpoints/12345",
    )

    assert enriched.schema_[0].properties[0].transformSourceObjects is None
    assert enriched.schema_[0].properties[0].transformLogic is None


def test_enrich_unity_lineage_missing_dependency():
    prop_id = SchemaProperty(id="id", name="id")
    schema_obj = SchemaObject(
        name="orders", physicalName="orders", properties=[prop_id]
    )
    contract = OpenDataContractStandard(
        apiVersion="3.1.0", id="test-contract", schema=[schema_obj]
    )

    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "databricks" or name == "databricks.sql":
            raise ImportError(f"No module named '{name}'")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        with pytest.raises(ImportError, match="databricks-sql-connector"):
            enrich_unity_lineage(
                contract,
                table_fqn="main.sales.orders",
                workspace_url="https://adb.example",
                token="token",
                sql_http_path="/sql/1.0/endpoints/12345",
            )
