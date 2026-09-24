"""Databricks authenticated-client construction boundary.

This module owns construction of an initialized Databricks WorkspaceClient.
Connection-hint resolution belongs to the calling composition boundary; missing
hints are intentionally left to the Databricks SDK unified-authentication chain.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient


def create_databricks_workspace_client(
    *,
    workspace_url: str | None = None,
    token: str | None = None,
    profile: str | None = None,
) -> WorkspaceClient:
    """Create a Databricks SDK client from explicit optional hints.

    This function does not read SemaPact configuration or mutate process-global
    environment variables. Callers that want project/global SemaPact settings
    resolve them before crossing this boundary.

    Omitted values are left for the SDK to resolve from its standard unified
    authentication chain.
    """
    kwargs: dict[str, str] = {}

    host = _clean_optional(workspace_url)
    if host:
        kwargs["host"] = host.rstrip("/")

    resolved_token = _clean_optional(token)
    if resolved_token:
        kwargs["token"] = resolved_token

    selected_profile = _clean_optional(profile)
    if selected_profile:
        kwargs["profile"] = selected_profile

    workspace_client_cls = _load_workspace_client_class()
    return workspace_client_cls(**kwargs)


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _load_workspace_client_class() -> Any:
    """Load the optional Databricks SDK only when client construction is used."""
    try:
        from databricks.sdk import WorkspaceClient
    except ImportError as exc:
        raise RuntimeError(
            'Databricks support requires the optional extra: pip install "semapact[databricks]"'
        ) from exc
    return WorkspaceClient
