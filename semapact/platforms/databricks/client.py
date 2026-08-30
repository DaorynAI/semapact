"""Databricks authenticated-client construction boundary.

This module owns construction of an initialized Databricks ``WorkspaceClient``.
Downstream platform capabilities such as observation consume the resulting
client and remain independent from the authentication mechanism used to create
it.

The initial supported path is explicit workspace URL + token. Additional
Databricks SDK authentication modes can be added here without changing
observation models or platform-operation signatures.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient


def create_databricks_workspace_client(
    *,
    workspace_url: str,
    token: str,
) -> WorkspaceClient:
    """Create an authenticated Databricks SDK client from explicit credentials.

    Credential resolution belongs to the caller/application boundary. This
    function intentionally performs no logging and never includes the token in
    validation errors.
    """
    host = workspace_url.strip() if workspace_url else ""
    if not host:
        raise ValueError("workspace_url is required")
    if not token or not token.strip():
        raise ValueError("token is required")

    workspace_client_cls = _load_workspace_client_class()
    return workspace_client_cls(host=host.rstrip("/"), token=token)


def _load_workspace_client_class() -> Any:
    """Load the optional Databricks SDK only when client construction is used."""
    try:
        from databricks.sdk import WorkspaceClient
    except ImportError as exc:
        raise RuntimeError(
            'Databricks support requires the optional extra: pip install "semapact[databricks]"'
        ) from exc
    return WorkspaceClient
