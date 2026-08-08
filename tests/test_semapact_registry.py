from datacontract.imports.importer_factory import importer_factory

import semapact.importers  # noqa: F401


def test_default_registry_contains_expected_importers():
    assert importer_factory.create("delta").import_format == "delta"
    assert importer_factory.create("delta-table").import_format == "delta-table"
    assert importer_factory.create("sql-folder").import_format == "sql-folder"
    assert importer_factory.create("delta-ddl").import_format == "delta-ddl"
