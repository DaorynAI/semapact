import pytest

from semapact.importers.sql_importer import SQLFolderImporter, _map_sql_type_to_odcs


def test_sql_folder_importer_rejects_missing_folder():
    with pytest.raises(ValueError, match="Folder does not exist"):
        SQLFolderImporter("sql-folder").import_source("/tmp/does-not-exist-12345", {})


def test_sql_folder_importer_rejects_empty_sql_folder(tmp_path):
    folder = tmp_path / "empty_product"
    folder.mkdir()
    with pytest.raises(ValueError, match="No .sql files found"):
        SQLFolderImporter("sql-folder").import_source(str(folder), {})


def test_sql_folder_importer_rejects_folder_with_no_create_table(tmp_path):
    folder = tmp_path / "no_table_product"
    folder.mkdir()
    (folder / "noop.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(ValueError, match="No CREATE TABLE statements found"):
        SQLFolderImporter("sql-folder").import_source(str(folder), {})


def test_map_sql_type_to_odcs_fallback_type():
    assert _map_sql_type_to_odcs("GEOGRAPHY") == "string"


def test_map_sql_type_to_odcs_supports_time_type():
    assert _map_sql_type_to_odcs("TIME") == "time"


def test_sql_folder_importer_import_source_updates_path(tmp_path):
    folder = tmp_path / "p1"
    folder.mkdir()
    (folder / "t.sql").write_text("CREATE TABLE t (id INT);", encoding="utf-8")
    importer = SQLFolderImporter("sql-folder")
    contract = importer.import_source(source=str(folder), import_args={})
    assert contract.name == "p1"


def test_sql_folder_importer_accepts_explicit_spark_dialect(tmp_path):
    folder = tmp_path / "spark_product"
    folder.mkdir()
    (folder / "t.sql").write_text("CREATE TABLE t (id BIGINT);", encoding="utf-8")

    contract = SQLFolderImporter("sql-folder").import_source(
        str(folder), {"dialect": "spark"}
    )
    assert contract.schema_ is not None
    assert contract.schema_[0].name == "t"


def test_sql_folder_importer_supports_template_tokens_and_max_length(tmp_path):
    folder = tmp_path / "templated"
    folder.mkdir()
    (folder / "t.sql").write_text(
        "CREATE TABLE ${orders_table} (customer_code VARCHAR(32), id INT);",
        encoding="utf-8",
    )

    contract = SQLFolderImporter("sql-folder").import_source(str(folder), {})
    assert contract.schema_ is not None
    table = contract.schema_[0]
    assert table.name == "orders_table"
    assert table.properties is not None
    fields = {item.name: item for item in table.properties if item.name}
    assert fields["customer_code"].logicalTypeOptions == {"maxLength": 32}
