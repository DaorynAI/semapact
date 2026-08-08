from __future__ import annotations

import logging
from typing import Any

from open_data_contract_standard.model import OpenDataContractStandard, SchemaObject

LOGGER = logging.getLogger(__name__)


def enrich_unity_lineage(
    contract: OpenDataContractStandard,
    *,
    table_fqn: str,
    workspace_url: str,
    token: str,
    sql_http_path: str | None = None,
) -> OpenDataContractStandard:
    """Extract lineage and logic from Unity Catalog using system tables."""
    try:
        from databricks import sql
    except ImportError as exc:
        raise ImportError(
            "The 'databricks-sql-connector' package is required to extract lineage. "
            "Please install it using: pip install databricks-sql-connector (or install with the [databricks] extra)."
        ) from exc

    if not sql_http_path:
        LOGGER.warning(
            "Skipping lineage extraction: --sql-http-path is required when using databricks-sql-connector"
        )
        return contract

    # Remove protocol prefix if accidentally included
    server_hostname = (
        workspace_url.replace("https://", "").replace("http://", "").rstrip("/")
    )

    try:
        with sql.connect(
            server_hostname=server_hostname,
            http_path=sql_http_path,
            access_token=token,
        ) as connection:
            with connection.cursor() as cursor:
                _apply_lineage_to_contract(contract, table_fqn, cursor)
                _apply_logic_to_contract(contract, table_fqn, cursor)
    except Exception as exc:
        LOGGER.warning(
            "Failed to fetch lineage or logic from Databricks system tables: %s", exc
        )

    return contract


def _apply_lineage_to_contract(
    contract: OpenDataContractStandard, table_fqn: str, cursor: Any
) -> None:
    schema_obj = _resolve_target_schema(contract, table_fqn=table_fqn)
    if schema_obj is None:
        return

    # Query system.access.column_lineage
    query = """
    SELECT source_table_full_name, source_column_name, target_column_name
    FROM system.access.column_lineage
    WHERE target_table_full_name = ?
    """
    try:
        cursor.execute(query, (table_fqn,))
        rows = cursor.fetchall()
    except Exception as exc:
        LOGGER.warning("Failed to query system.access.column_lineage: %s", exc)
        return

    col_mapping: dict[str, list[str]] = {}

    for row in rows:
        source_table = row.source_table_full_name
        source_column = row.source_column_name
        target_column = row.target_column_name

        if not target_column or not source_column or not source_table:
            continue

        target_col_lower = target_column.lower()
        if target_col_lower not in col_mapping:
            col_mapping[target_col_lower] = []

        full_source = f"{source_table}.{source_column}"
        if full_source not in col_mapping[target_col_lower]:
            col_mapping[target_col_lower].append(full_source)

    fields = {
        item.name.lower(): item for item in (schema_obj.properties or []) if item.name
    }

    for col_name, sources in col_mapping.items():
        property_obj = fields.get(col_name)
        if property_obj:
            existing = property_obj.transformSourceObjects or []
            for s in sources:
                if s not in existing:
                    existing.append(s)
            if existing:
                property_obj.transformSourceObjects = existing


def _apply_logic_to_contract(
    contract: OpenDataContractStandard, table_fqn: str, cursor: Any
) -> None:
    schema_obj = _resolve_target_schema(contract, table_fqn=table_fqn)
    if schema_obj is None:
        return

    # We want to find the latest statement that wrote to this table
    # We can join table_lineage with query_history.
    # Note: Using `target_table_full_name = ?` to find writes.
    query = """
    SELECT qh.statement_text
    FROM system.access.table_lineage tl
    JOIN system.access.query_history qh ON tl.statement_id = qh.statement_id
    WHERE tl.target_table_full_name = ?
      AND tl.source_table_full_name IS NOT NULL
    ORDER BY tl.event_time DESC
    LIMIT 1
    """
    try:
        cursor.execute(query, (table_fqn,))
        row = cursor.fetchone()
    except Exception as exc:
        LOGGER.warning("Failed to query system.access.query_history for logic: %s", exc)
        return

    if row and row.statement_text:
        statement = row.statement_text
        # Apply the logic to all properties that don't have one
        for prop in schema_obj.properties or []:
            if not prop.transformLogic:
                prop.transformLogic = statement


def _resolve_target_schema(
    contract: OpenDataContractStandard, *, table_fqn: str
) -> SchemaObject | None:
    schema_items = contract.schema_ or []
    if not schema_items:
        return None
    short_name = table_fqn.split(".")[-1].strip().lower()
    for item in schema_items:
        if (item.physicalName or "").strip().lower() == short_name:
            return item
    for item in schema_items:
        if (item.name or "").strip().lower() == short_name:
            return item
    return schema_items[0]
