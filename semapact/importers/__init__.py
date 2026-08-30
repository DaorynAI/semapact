"""SemaPact importer registrations.

Optional importer dependencies are registered only when their provider package
is installed, so one platform extra does not require unrelated platforms.
"""

from __future__ import annotations

from importlib.util import find_spec

from datacontract.imports.importer_factory import importer_factory

from semapact.importers.sql_importer import SQLFolderImporter

__all__ = ["SQLFolderImporter"]

# SQL-folder support has no provider-specific optional dependency beyond the
# base SemaPact/datacontract-cli installation.
importer_factory.register_importer("sql-folder", SQLFolderImporter)
importer_factory.register_importer("delta-ddl", SQLFolderImporter)

# Delta support depends on the separate ``deltalake`` extra. Import and register
# it only when that optional dependency is actually available.
if find_spec("deltalake") is not None:
    from semapact.importers.delta_importer import DeltaTableImporter

    importer_factory.register_importer("delta", DeltaTableImporter)
    importer_factory.register_importer("delta-table", DeltaTableImporter)
    __all__.append("DeltaTableImporter")
