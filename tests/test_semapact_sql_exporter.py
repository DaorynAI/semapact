import yaml

import re

import pytest

from semapact.exporters.sql_exporter import export_contract_to_spark_sql


def test_export_contract_to_spark_sql_uses_physical_schema_names_from_sample():
    ddl = export_contract_to_spark_sql("examples/sample_odcs.yaml")

    assert "CREATE OR REPLACE TABLE tbl_1" in ddl
    assert "CREATE OR REPLACE TABLE receivers_master" in ddl
    assert re.search(r"\btxn_ref_dt\s+date\b", ddl, flags=re.IGNORECASE)
    assert re.search(
        r"\brcvr_id\s+varchar\(18\)\s+primary key\b", ddl, flags=re.IGNORECASE
    )
    assert 'COMMENT "Provides core payment metrics"' in ddl
    assert " None" not in ddl


def test_export_contract_to_spark_sql_with_unity_catalog_prefix():
    ddl = export_contract_to_spark_sql(
        "examples/sample_odcs.yaml",
        unity_catalog="main",
        unity_schema="silver",
    )

    assert "CREATE OR REPLACE TABLE main.silver.tbl_1" in ddl
    assert "CREATE OR REPLACE TABLE main.silver.receivers_master" in ddl


def test_export_contract_to_spark_sql_requires_both_unity_catalog_and_schema():
    with pytest.raises(ValueError, match="provided together"):
        export_contract_to_spark_sql("examples/sample_odcs.yaml", unity_catalog="main")


def test_export_contract_to_spark_sql_appends_not_null_constraint_from_quality_rule():
    ddl = export_contract_to_spark_sql("examples/sample_odcs.yaml")

    assert "ALTER TABLE tbl_1" in ddl
    assert "ALTER COLUMN rcvr_cntry_code SET NOT NULL" in ddl


def test_export_contract_to_spark_sql_supports_temporal_and_scalar_fixture(
    sample_temporal_types_contract_path,
):
    ddl = export_contract_to_spark_sql(sample_temporal_types_contract_path)

    assert "CREATE OR REPLACE TABLE temporal_events" in ddl
    assert re.search(r"\bbusiness_date\s+DATE\s+not null\b", ddl, flags=re.IGNORECASE)
    assert re.search(r"\bevent_ts\s+TIMESTAMP\s+not null\b", ddl, flags=re.IGNORECASE)
    assert re.search(r"\bevent_ts_ntz\s+TIMESTAMP_NTZ\b", ddl, flags=re.IGNORECASE)
    assert re.search(r"\bis_active\s+BOOLEAN\s+not null\b", ddl, flags=re.IGNORECASE)
    assert re.search(r"\braw_payload\s+BINARY\b", ddl, flags=re.IGNORECASE)


def test_export_contract_to_spark_sql_supports_nested_fixture(
    sample_nested_types_contract_path,
):
    ddl = export_contract_to_spark_sql(sample_nested_types_contract_path)

    assert "CREATE OR REPLACE TABLE nested_payloads" in ddl
    assert "payload STRUCT" in ddl
    assert "events ARRAY<STRUCT<event_id: STRING, event_ts: TIMESTAMP>>" in ddl
    assert "attributes MAP<STRING, ARRAY<STRUCT<k: STRING, v: STRING>>>" in ddl


def test_export_contract_to_spark_sql_with_external_location():
    with open("examples/sample_odcs.yaml", "r") as f:
        contract = yaml.safe_load(f)

    # Inject the custom property into the first schema object
    if "schema" in contract and len(contract["schema"]) > 0:
        contract["schema"][0]["customProperties"] = [
            {"property": "semapact.table.location", "value": "s3://my-bucket/path/"}
        ]

    # 1. databricks mode
    ddl_databricks = export_contract_to_spark_sql(
        contract, sql_server_type="databricks"
    )
    assert "LOCATION 's3://my-bucket/path/'" in ddl_databricks
    assert "CREATE OR REPLACE TABLE tbl_1" in ddl_databricks
    assert "USING delta" in ddl_databricks

    # 2. spark mode
    ddl_spark = export_contract_to_spark_sql(contract, sql_server_type="spark")
    assert "LOCATION 's3://my-bucket/path/'" in ddl_spark
    assert "CREATE TABLE tbl_1" in ddl_spark
    assert "USING delta" in ddl_spark

    # 3. postgres mode (should not inject location or format/partitioning)
    ddl_postgres = export_contract_to_spark_sql(contract, sql_server_type="postgres")
    assert "LOCATION 's3://my-bucket/path/'" not in ddl_postgres
    assert "USING delta" not in ddl_postgres


def test_export_contract_to_spark_sql_with_schema_name():
    with open("examples/sample_odcs.yaml", "r") as f:
        contract = yaml.safe_load(f)

    # Inject locations to multiple tables
    if "schema" in contract and len(contract["schema"]) > 1:
        contract["schema"][0]["customProperties"] = [
            {"property": "semapact.table.location", "value": "s3://my-bucket/tbl_1/"}
        ]
        contract["schema"][1]["customProperties"] = [
            {"property": "semapact.table.location", "value": "s3://my-bucket/tbl_2/"}
        ]

    # Export only tbl_1
    ddl = export_contract_to_spark_sql(
        contract, sql_server_type="databricks", schema_name="tbl_1"
    )
    assert "CREATE OR REPLACE TABLE tbl_1" in ddl
    assert "LOCATION 's3://my-bucket/tbl_1/'" in ddl
    assert "CREATE OR REPLACE TABLE receivers_master" not in ddl
    assert "LOCATION 's3://my-bucket/tbl_2/'" not in ddl


def test_export_contract_to_spark_sql_with_partitioning_and_format():
    contract = {
        "apiVersion": "v3.1.0",
        "kind": "DataContract",
        "id": "my-contract",
        "schema": [
            {
                "name": "my_table",
                "description": "My table description",
                "customProperties": [
                    {"property": "semapact.table.location", "value": "s3://my-bucket/my_table/"},
                    {"property": "semapact.table.format", "value": "parquet"}
                ],
                "properties": [
                    {
                        "name": "id",
                        "type": "string",
                        "partitioned": True,
                        "partitionKeyPosition": 2
                    },
                    {
                        "name": "dt",
                        "type": "string",
                        "partitioned": True,
                        "partitionKeyPosition": 1
                    },
                    {
                        "name": "val",
                        "type": "integer"
                    }
                ]
            }
        ]
    }

    ddl = export_contract_to_spark_sql(contract, sql_server_type="databricks")
    # Verify the DDL has the correct order of USING -> PARTITIONED BY -> LOCATION -> COMMENT
    # The order must be:
    # USING parquet
    # PARTITIONED BY (dt, id)
    # LOCATION 's3://my-bucket/my_table/'
    # COMMENT "My table description"

    assert "USING parquet" in ddl
    assert "PARTITIONED BY (dt, id)" in ddl
    assert "LOCATION 's3://my-bucket/my_table/'" in ddl
    assert 'COMMENT "My table description"' in ddl

    # Validate correct relative ordering
    idx_using = ddl.index("USING parquet")
    idx_partition = ddl.index("PARTITIONED BY (dt, id)")
    idx_location = ddl.index("LOCATION 's3://my-bucket/my_table/'")
    idx_comment = ddl.index('COMMENT "My table description"')

    assert idx_using < idx_partition < idx_location < idx_comment

