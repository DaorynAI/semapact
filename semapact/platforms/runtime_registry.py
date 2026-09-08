"""Composition root for runtime provider implementations."""

from __future__ import annotations

from semapact.exceptions import ValidationError
from semapact.observation import RuntimeProvider, RuntimeProviderRegistry


def create_runtime_provider_registry(platform: str) -> RuntimeProviderRegistry:
    """Create a registry containing the selected supported runtime provider.

    Provider construction remains outside reconciliation and CLI semantics. Only the
    selected provider is initialized so unrelated optional dependencies or credentials
    are never required.
    """
    normalized = platform.strip().casefold()
    if normalized == "databricks":
        return RuntimeProviderRegistry((_create_databricks_provider(),))
    raise ValidationError(
        f"Unsupported runtime provider '{platform}'. Supported providers: databricks"
    )


def _create_databricks_provider() -> RuntimeProvider:
    from semapact.platforms.databricks import (
        DatabricksRuntimeProvider,
        create_databricks_workspace_client,
    )

    client = create_databricks_workspace_client()
    config = getattr(client, "config", None)
    source_identifier = getattr(config, "host", None)
    if not isinstance(source_identifier, str) or not source_identifier.strip():
        raise RuntimeError("Databricks SDK did not resolve a workspace host")
    return DatabricksRuntimeProvider(
        client=client,
        source_identifier=source_identifier,
    )
