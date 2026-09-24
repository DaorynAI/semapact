"""Unity Catalog metadata import into canonical ODCS contracts."""

from __future__ import annotations

import logging
from typing import Any

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.importers.unity_relationships import (
    enrich_unity_contract_relationships,
)

LOGGER = logging.getLogger(__name__)


def import_unity_contract(
    *,
    table_fqn: str,
    workspace_url: str | None = None,
    token: str | None = None,
    profile: str | None = None,
    sql_http_path: str | None = None,
    extract_lineage: bool = False,
    client: Any | None = None,
) -> OpenDataContractStandard:
    """Import one UC table or one entire UC schema as an ODCS data product.

    Authentication/configuration is resolved at this import composition boundary.
    The importer itself uses only the official Databricks SDK client and never
    mutates process-global environment variables.

    Runtime lineage remains observation evidence and is not projected into ODCS.
    """
    del sql_http_path

    if extract_lineage:
        raise ValueError(
            "Unity lineage is runtime observation evidence and cannot be "
            "projected into ODCS during import"
        )

    parts = tuple(part.strip() for part in table_fqn.split("."))
    if len(parts) not in {2, 3} or not all(parts):
        raise ValueError(
            "Unity import source must use catalog.schema or catalog.schema.table"
        )

    from datacontract.imports.unity_importer import (
        convert_unity_schema,
        create_odcs,
    )

    from semapact.platforms.databricks.configuration import (
        create_configured_databricks_workspace_client,
    )
    from semapact.platforms.databricks.discovery import discover_databricks_tables

    ws_client = client or create_configured_databricks_workspace_client(
        workspace_url=workspace_url,
        token=token,
        profile=profile,
    )

    is_schema_level = len(parts) == 2
    if is_schema_level:
        catalog, schema_name = parts
        tables_to_import = discover_databricks_tables(
            client=ws_client,
            catalog_name=catalog,
            schema_name=schema_name,
        )
        if not tables_to_import:
            raise ValueError(
                f"No tables discovered in Unity Catalog schema {table_fqn}"
            )
    else:
        tables_to_import = (table_fqn,)

    LOGGER.info(
        "Importing %d Unity Catalog table(s) from %s",
        len(tables_to_import),
        table_fqn,
    )

    imported = create_odcs()
    imported.schema_ = []
    table_metadata: dict[str, dict[str, Any]] = {}
    for table_name in tables_to_import:
        table_info = ws_client.tables.get(table_name)
        imported = convert_unity_schema(imported, table_info)
        as_dict = getattr(table_info, "as_dict", None)
        if not callable(as_dict):
            raise TypeError("Databricks TableInfo must expose as_dict()")
        metadata = as_dict()
        if not isinstance(metadata, dict):
            raise TypeError("Databricks TableInfo.as_dict() must return a dict")
        table_metadata[table_name] = metadata

    if is_schema_level:
        catalog, schema_name = parts
        imported.id = f"{catalog}-{schema_name}-product"
        imported.name = f"{catalog.capitalize()} {schema_name.capitalize()} Data Product"
        imported.status = "active"

    return enrich_unity_contract_relationships(
        imported,
        table_metadata=table_metadata,
    )
