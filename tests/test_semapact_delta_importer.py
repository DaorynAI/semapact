import pandas as pd
from deltalake import write_deltalake

import semapact.importers.delta_importer as delta_importer


def test_delta_importer_builds_odcs_contract_from_real_local_delta_table(tmp_path):
    table_path = tmp_path / "finance_transactions"
    data = pd.DataFrame(
        {
            "id": pd.Series([1, 2], dtype="int64"),
            "amount": pd.Series([10.5, 22.75], dtype="float64"),
            "processed_at": pd.to_datetime(
                ["2026-04-03T10:00:00Z", "2026-04-03T10:01:00Z"], utc=True
            ),
        }
    )
    write_deltalake(str(table_path), data, mode="overwrite")

    importer = delta_importer.DeltaTableImporter("delta")
    contract = importer.import_source(str(table_path), {})

    assert contract.name == "finance_transactions"
    assert contract.version == "1.0.0"
    assert contract.schema_ is not None
    table = contract.schema_[0]
    assert table.id == "finance_transactions"
    assert table.properties is not None
    fields = {item.name: item for item in table.properties if item.name}
    assert fields["id"].logicalType == "integer"
    assert fields["amount"].logicalType == "number"
    assert fields["processed_at"].logicalType == "timestamp"

    table_cp = {item.property: item.value for item in table.customProperties or []}
    assert table_cp["semapact.table.location"] == str(table_path)
    assert "semapact.delta.uri" not in table_cp
    assert "semapact.delta.version" not in table_cp


def test_delta_importer_builds_odcs_contract(
    monkeypatch, delta_finance_transactions_schema_path
):
    class FakeSchema:
        @staticmethod
        def json():
            return delta_finance_transactions_schema_path.read_text(encoding="utf-8")

    class FakeMetadata:
        description = "Finance transactions"
        configuration = {}
        partition_columns = ["id"]

    class FakeDeltaTable:
        def __init__(self, _uri, *, storage_options=None, **_kwargs):
            self._uri = _uri
            self._storage_options = storage_options

        def schema(self):
            return FakeSchema()

        def metadata(self):
            return FakeMetadata()

        @staticmethod
        def version():
            return 12

    monkeypatch.setattr(delta_importer, "DeltaTable", FakeDeltaTable)

    importer = delta_importer.DeltaTableImporter("delta")
    contract = importer.import_source("s3://lake/silver/finance_transactions", {})

    assert contract.name == "finance_transactions"
    assert contract.version == "1.0.0"
    assert contract.description is not None
    assert contract.description.usage == "Finance transactions"
    assert contract.schema_ is not None
    table = contract.schema_[0]
    assert table.id == "finance_transactions"
    assert table.properties is not None
    assert table.properties[0].name == "id"
    assert table.properties[0].required is True
    assert table.properties[0].partitioned is True
    assert table.properties[0].partitionKeyPosition == 1
    assert table.properties[1].logicalType == "number"
    assert table.properties[1].logicalTypeOptions is None
    payload_field = next(item for item in table.properties if item.name == "payload")
    assert payload_field.logicalType == "object"
    assert payload_field.properties is not None
    assert payload_field.properties[0].name == "source"
    events_field = next(item for item in table.properties if item.name == "events")
    assert events_field.logicalType == "array"
    assert events_field.items is not None
    assert events_field.items.logicalType == "object"
    attributes_field = next(
        item for item in table.properties if item.name == "attributes"
    )
    assert attributes_field.logicalType == "object"
    assert attributes_field.logicalTypeOptions is not None
    assert (
        str(attributes_field.logicalTypeOptions["keyType"]).lower().startswith("string")
    )

    table_cp = {item.property: item.value for item in table.customProperties or []}
    assert table_cp["semapact.table.location"] == "s3://lake/silver/finance_transactions"
    assert "semapact.delta.uri" not in table_cp
    assert "semapact.delta.version" not in table_cp
    assert "semapact.delta.partitionColumns" not in table_cp


def test_delta_importer_supports_multiple_tables(
    monkeypatch, delta_minimal_schema_path
):
    class FakeSchema:
        @staticmethod
        def json():
            return delta_minimal_schema_path.read_text(encoding="utf-8")

    class FakeMetadata:
        description = None
        configuration = {}
        partition_columns = []

    class FakeDeltaTable:
        def __init__(self, _uri, *, storage_options=None, **_kwargs):
            self._uri = _uri
            self._storage_options = storage_options

        def schema(self):
            return FakeSchema()

        def metadata(self):
            return FakeMetadata()

        @staticmethod
        def version():
            return 3

    monkeypatch.setattr(delta_importer, "DeltaTable", FakeDeltaTable)

    importer = delta_importer.DeltaTableImporter("delta")
    contract = importer.import_source(
        "s3://lake/silver/orders",
        {
            "table_uris": ["s3://lake/silver/payments"],
            "dataset_name": "finance_product",
        },
    )

    assert contract.name == "finance_product"
    assert contract.schema_ is not None
    assert len(contract.schema_) == 2
    table_names = {item.name for item in contract.schema_}
    assert table_names == {"orders", "payments"}


def test_delta_import_to_spark_sql_export_integration(tmp_path):
    from pathlib import Path
    from semapact.exporters.sql_exporter import export_contract_to_spark_sql

    table_path = tmp_path / "finance_transactions"
    data = pd.DataFrame(
        {
            "id": pd.Series([1, 2], dtype="int64"),
            "amount": pd.Series([10.5, 22.75], dtype="float64"),
            "processed_date": ["2026-04-03", "2026-04-03"],
        }
    )
    write_deltalake(str(table_path), data, mode="overwrite", partition_by=["processed_date"])

    importer = delta_importer.DeltaTableImporter("delta")
    contract = importer.import_source(str(table_path), {})

    # Export using the custom SQL exporter
    ddl = export_contract_to_spark_sql(contract, sql_server_type="databricks")

    assert "CREATE OR REPLACE TABLE finance_transactions" in ddl
    assert "id BIGINT" in ddl or "id LONG" in ddl or "id bigint" in ddl or "id long" in ddl
    assert "amount DOUBLE" in ddl or "amount double" in ddl
    assert "processed_date STRING" in ddl or "processed_date string" in ddl
    assert "USING delta" in ddl
    assert "PARTITIONED BY (processed_date)" in ddl

    expected_path = Path(table_path).as_posix()
    assert expected_path in ddl.replace("\\", "/")

