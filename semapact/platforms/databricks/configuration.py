"""Databricks connection-hint resolution for SemaPact composition roots."""

from __future__ import annotations

import os
from dataclasses import dataclass

from pydantic import ValidationError as PydanticValidationError

from semapact.core.config import config_manager
from semapact.core.config_schema import parse_databricks_config
from semapact.exceptions import ValidationError


@dataclass(frozen=True)
class DatabricksConnectionHints:
    """Resolved optional hints passed to the Databricks SDK client factory."""

    workspace_url: str | None = None
    token: str | None = None
    profile: str | None = None


def resolve_databricks_connection_hints(
    *,
    workspace_url: str | None = None,
    token: str | None = None,
    profile: str | None = None,
) -> DatabricksConnectionHints:
    """Resolve explicit hints, SemaPact overrides, then project/global config.

    Standard Databricks environment variables and ~/.databrickscfg are not read
    here. When a hint remains absent, the official SDK resolves it through its
    normal unified-authentication chain.
    """
    try:
        configured = parse_databricks_config(
            config_manager.get("databricks", default=None)
        )
    except PydanticValidationError as exc:
        raise ValidationError(f"Invalid databricks configuration: {exc}") from exc

    return DatabricksConnectionHints(
        workspace_url=_first_nonblank(
            workspace_url,
            os.environ.get("SEMAPACT_DATABRICKS_WORKSPACE_URL"),
            configured.workspace_url if configured is not None else None,
        ),
        token=_first_nonblank(
            token,
            os.environ.get("SEMAPACT_DATABRICKS_TOKEN"),
            configured.token if configured is not None else None,
        ),
        profile=_first_nonblank(
            profile,
            os.environ.get("SEMAPACT_DATABRICKS_PROFILE"),
            configured.profile if configured is not None else None,
        ),
    )


def _first_nonblank(*values: str | None) -> str | None:
    for value in values:
        if value is None:
            continue
        cleaned = value.strip()
        if cleaned:
            return cleaned
    return None
