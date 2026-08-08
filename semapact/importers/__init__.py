from datacontract.imports.importer_factory import importer_factory

from semapact.importers.delta_importer import DeltaTableImporter
from semapact.importers.sql_importer import SQLFolderImporter

# Register SemaPact custom importers with datacontract-cli importer factory.
importer_factory.register_importer("delta", DeltaTableImporter)
importer_factory.register_importer("delta-table", DeltaTableImporter)
importer_factory.register_importer("sql-folder", SQLFolderImporter)
importer_factory.register_importer("delta-ddl", SQLFolderImporter)

__all__ = [
    "DeltaTableImporter",
    "SQLFolderImporter",
]
