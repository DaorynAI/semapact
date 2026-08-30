"""Databricks authenticated-client construction boundary.

This module owns construction of an initialized Databricks ``WorkspaceClient``.
Downstream platform capabilities such as observation consume the resulting
client and remain independent from the authentication mechanism used to create
it.

SemaPact forwards only the connection/authentication hints supplied by the
caller. The Databricks SDK remains responsible for selecting and validating the
authentication mechanism, including its default/unified authentication chain.
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
    """Create a Databricks SDK client from the auth hints the caller has.

    SemaPact does not choose an authentication provider. Non-empty values are
    forwarded to ``WorkspaceClient`` and omitted values are left for the SDK to
    resolve from its standard configuration/authentication chain. Calling this
    function with no arguments is therefore equivalent to ``WorkspaceClient()``.

    The function performs no credential logging or serialization.
    """
    kwargs: dict[str, str] = {}

    host = _clean_optional(workspace_url)
    if host:
        kwargs["host"] = host.rstrip("/")

    if token and token.strip():
        kwargs["token"] = token

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
