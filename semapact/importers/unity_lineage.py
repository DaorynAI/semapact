from __future__ import annotations

import logging

from open_data_contract_standard.model import OpenDataContractStandard, SchemaObject

from semapact.observation.lineage import (
    ObservedLineageEvidence,
    ObservedLineageEvidenceType,
    ObservedLineageResult,
)
from semapact.platforms.databricks.lineage import observe_databricks_lineage

LOGGER = logging.getLogger(__name__)


def enrich_unity_lineage(
    contract: OpenDataContractStandard,
    *,
    table_fqn: str,
    workspace_url: str,
    token: str,
    sql_http_path: str | None = None,
) -> OpenDataContractStandard:
    """Compatibility projection of normalized Databricks lineage into ODCS fields.

    Runtime lineage retrieval is owned by the read-only Databricks lineage adapter.
    This legacy importer remains available for callers that explicitly want ODCS
    enrichment; it no longer defines or retrieves lineage semantics itself.
    """
    if not sql_http_path:
        LOGGER.warning(
            "Skipping lineage extraction: --sql-http-path is required when using databricks-sql-connector"
        )
        return contract

    try:
        from databricks import sql
    except ImportError as exc:
        raise ImportError(
            "The 'databricks-sql-connector' package is required to extract lineage. "
            "Please install it using: pip install databricks-sql-connector (or install with the [databricks] extra)."
        ) from exc

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
                result = observe_databricks_lineage(
                    cursor=cursor,
                    table_fqn=table_fqn,
                    source_identifier=workspace_url,
                )
                _apply_lineage_evidence(contract, table_fqn=table_fqn, result=result)
    except Exception as exc:
        LOGGER.warning(
            "Failed to fetch lineage or logic from Databricks system tables: %s", exc
        )

    return contract


def _apply_lineage_evidence(
    contract: OpenDataContractStandard,
    *,
    table_fqn: str,
    result: ObservedLineageResult,
) -> None:
    schema_obj = _resolve_target_schema(contract, table_fqn=table_fqn)
    if schema_obj is None:
        return

    target_key = table_fqn.casefold()
    fields = {
        item.name.casefold(): item
        for item in (schema_obj.properties or [])
        if item.name
    }

    for item in result.evidence:
        if item.evidence_type is not ObservedLineageEvidenceType.COLUMN:
            continue
        if _asset_reference(item, target=True).casefold() != target_key:
            continue
        if not item.target_property or not item.source_property:
            continue
        source_table = _asset_reference(item, target=False)
        if not source_table:
            continue
        property_obj = fields.get(item.target_property.casefold())
        if property_obj is None:
            continue
        source = f"{source_table}.{item.source_property}"
        existing = list(property_obj.transformSourceObjects or [])
        if source not in existing:
            existing.append(source)
        property_obj.transformSourceObjects = existing

    # Legacy compatibility only: an explicit enrichment request may project the
    # latest query text into transformLogic. Runtime observation keeps this text
    # as non-authoritative QUERY evidence and never mutates the contract.
    query_evidence = [
        item
        for item in result.evidence
        if item.evidence_type is ObservedLineageEvidenceType.QUERY
        and item.statement_text
        and _asset_reference(item, target=True).casefold() == target_key
    ]
    if query_evidence:
        latest = max(query_evidence, key=_query_recency_key)
        for prop in schema_obj.properties or []:
            if not prop.transformLogic:
                prop.transformLogic = latest.statement_text


def _query_recency_key(item: ObservedLineageEvidence) -> tuple[str, str]:
    recorded_at = item.capture_context.recorded_at
    return (
        recorded_at.isoformat() if recorded_at is not None else "",
        item.statement_reference or "",
    )


def _asset_reference(item: ObservedLineageEvidence, *, target: bool) -> str:
    asset = item.target_asset if target else item.source_asset
    reference = item.target_reference if target else item.source_reference
    if asset is not None:
        return ".".join((*asset.namespace, asset.asset))
    return reference or ""


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
