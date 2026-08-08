from datacontract.imports.importer_factory import importer_factory

import semapact.importers  # noqa: F401
from semapact.importers.sql_importer import SQLFolderImporter


def test_sql_folder_importer_parses_real_sparksql_external_table_ddl(
    spark_ddl_adls2_product_dir,
):
    importer = SQLFolderImporter("sql-folder")
    contract = importer.import_source(str(spark_ddl_adls2_product_dir), {})

    assert contract.name == "adls2_product"
    assert contract.schema_ is not None
    assert len(contract.schema_) == 1

    table = contract.schema_[0]
    assert table.id == "orders_external"
    assert table.name == "orders_external"
    assert table.physicalType == "external-table"
    table_props = {item.property: item.value for item in table.customProperties or []}
    assert table_props["semapact.table.external"] == "true"
    assert table_props["semapact.table.format"] == "DELTA"
    assert table_props["semapact.table.location"].startswith("abfss://silver@")

    assert table.properties is not None
    id_field = next(item for item in table.properties if item.name == "id")
    assert id_field.id == "id"
    assert str(id_field.physicalType).lower().startswith("bigint")
    assert id_field.required is True
    assert id_field.description == "Order id"

    amount_field = next(item for item in table.properties if item.name == "amount")
    assert amount_field.logicalTypeOptions == {"precision": 18, "scale": 2}

    payload_field = next(item for item in table.properties if item.name == "payload")
    assert payload_field.logicalType == "object"
    nested_names = {item.name for item in payload_field.properties or []}
    assert nested_names == {"source", "metrics", "labels"}
    events_field = next(item for item in table.properties if item.name == "events")
    assert events_field.logicalType == "array"
    assert events_field.items is not None
    assert events_field.items.logicalType == "object"
    attributes_field = next(
        item for item in table.properties if item.name == "attributes"
    )
    assert attributes_field.logicalType == "object"
    assert attributes_field.items is not None
    assert attributes_field.items.logicalType == "array"


def test_sql_folder_importer_multiple_files_generate_one_contract_with_all_tables(
    spark_ddl_finance_product_dir,
):
    importer = SQLFolderImporter("sql-folder")
    contract = importer.import_source(str(spark_ddl_finance_product_dir), {})

    # One import call should produce one ODCS contract containing all table schemas.
    assert contract.name == "finance_product"
    assert contract.id == "finance_product"
    assert contract.schema_ is not None
    assert len(contract.schema_) == 3

    table_names = {item.name for item in contract.schema_}
    assert table_names == {"accounts", "transactions", "balances"}


def test_sql_folder_importer_extracts_primary_key_unique_and_partition_metadata(
    spark_ddl_risk_product_dir,
):
    contract = SQLFolderImporter("sql-folder").import_source(
        str(spark_ddl_risk_product_dir), {}
    )
    assert contract.schema_ is not None
    table = contract.schema_[0]

    assert table.description == "Event fact table"
    assert table.properties is not None
    fields = {item.name: item for item in table.properties if item.name}
    assert fields["event_id"].primaryKey is True
    assert fields["event_id"].primaryKeyPosition == 1
    assert fields["source"].unique is True
    assert fields["event_date"].partitioned is True
    assert fields["event_date"].partitionKeyPosition == 1


def test_sql_folder_importer_extracts_foreign_key_relationships(
    spark_ddl_delta_relationship_product_dir,
):
    contract = SQLFolderImporter("sql-folder").import_source(
        str(spark_ddl_delta_relationship_product_dir), {}
    )
    assert contract.schema_ is not None
    tables = {item.name: item for item in contract.schema_}
    child = tables["children"]
    assert child.properties is not None
    fields = {item.name: item for item in child.properties if item.name}

    assert fields["parent_id"].relationships is not None
    assert fields["parent_id"].relationships[0].type == "foreignKey"
    assert fields["parent_id"].relationships[0].to == "parents.id"

    assert fields["inline_parent_id"].relationships is not None
    assert fields["inline_parent_id"].relationships[0].type == "foreignKey"
    assert fields["inline_parent_id"].relationships[0].to == "parents.id"

    assert child.relationships is not None
    assert child.relationships[0].type == "foreignKey"
    assert child.relationships[0].from_ == ["parent_tenant", "parent_code"]
    assert child.relationships[0].to == ["parents.tenant", "parents.code"]


def test_delta_ddl_alias_sets_source_marker(spark_ddl_delta_relationship_product_dir):
    importer = importer_factory.create("delta-ddl")
    contract = importer.import_source(str(spark_ddl_delta_relationship_product_dir), {})
    source_props = {
        item.property: item.value for item in contract.customProperties or []
    }
    assert source_props["semapact.source"] == "delta-ddl"
