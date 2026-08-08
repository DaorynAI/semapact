from datacontract.imports.importer_factory import importer_factory

import semapact.importers  # noqa: F401


def test_importer_factory_registers_semapact_importers():
    delta_importer = importer_factory.create("delta")
    delta_table_importer = importer_factory.create("delta-table")
    sql_importer = importer_factory.create("sql-folder")
    delta_ddl_importer = importer_factory.create("delta-ddl")

    assert delta_importer.import_format == "delta"
    assert delta_table_importer.import_format == "delta-table"
    assert sql_importer.import_format == "sql-folder"
    assert delta_ddl_importer.import_format == "delta-ddl"
