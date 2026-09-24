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
    """Create a Databricks SDK client from caller hints, ConfigManager, or SDK defaults.

    Precedence for each hint:
    1. Explicit caller arguments (workspace_url, token, profile)
    2. Product configuration via ConfigManager (databricks.workspace_url / host, databricks.token, databricks.profile)
    3. Databricks SDK Unified Authentication chain (DATABRICKS_HOST, ~/.databrickscfg)

    The function performs no credential logging or serialization.
    """
    from semapact.core.config import config_manager

    resolved_workspace_url = (
        _clean_optional(workspace_url)
        or _clean_optional(
            config_manager.get(
                "databricks.workspace_url",
                env_var="SEMAPACT_DATABRICKS_WORKSPACE_URL",
            )
        )
        or _clean_optional(config_manager.get("databricks.host"))
    )
    resolved_token = _clean_optional(token) or _clean_optional(
        config_manager.get("databricks.token", env_var="SEMAPACT_DATABRICKS_TOKEN")
    )
    resolved_profile = _clean_optional(profile) or _clean_optional(
        config_manager.get("databricks.profile", env_var="SEMAPACT_DATABRICKS_PROFILE")
    )

    kwargs: dict[str, str] = {}
    if resolved_workspace_url:
        kwargs["host"] = resolved_workspace_url.rstrip("/")

    if resolved_token:
        kwargs["token"] = resolved_token

    if resolved_profile:
        kwargs["profile"] = resolved_profile

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
