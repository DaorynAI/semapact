from __future__ import annotations

import pytest

from semapact.exceptions import ValidationError
from semapact.platforms.databricks.configuration import (
    resolve_databricks_connection_hints,
)


def test_databricks_connection_hints_use_typed_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEMAPACT_DATABRICKS_WORKSPACE_URL", raising=False)
    monkeypatch.delenv("SEMAPACT_DATABRICKS_TOKEN", raising=False)
    monkeypatch.delenv("SEMAPACT_DATABRICKS_PROFILE", raising=False)
    monkeypatch.setattr(
        "semapact.platforms.databricks.configuration.config_manager.get",
        lambda key, default=None: {
            "workspace_url": " https://config.example/ ",
            "token": " config-token ",
            "profile": " config-profile ",
        }
        if key == "databricks"
        else default,
    )

    hints = resolve_databricks_connection_hints()

    assert hints.workspace_url == "https://config.example/"
    assert hints.token == "config-token"
    assert hints.profile == "config-profile"


def test_databricks_connection_hints_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "SEMAPACT_DATABRICKS_WORKSPACE_URL",
        "https://env.example",
    )
    monkeypatch.setenv("SEMAPACT_DATABRICKS_TOKEN", "env-token")
    monkeypatch.setenv("SEMAPACT_DATABRICKS_PROFILE", "env-profile")
    monkeypatch.setattr(
        "semapact.platforms.databricks.configuration.config_manager.get",
        lambda key, default=None: {
            "workspace_url": "https://config.example",
            "token": "config-token",
            "profile": "config-profile",
        }
        if key == "databricks"
        else default,
    )

    env_hints = resolve_databricks_connection_hints()
    assert env_hints.workspace_url == "https://env.example"
    assert env_hints.token == "env-token"
    assert env_hints.profile == "env-profile"

    explicit_hints = resolve_databricks_connection_hints(
        workspace_url="https://explicit.example",
        token="explicit-token",
        profile="explicit-profile",
    )
    assert explicit_hints.workspace_url == "https://explicit.example"
    assert explicit_hints.token == "explicit-token"
    assert explicit_hints.profile == "explicit-profile"


def test_databricks_connection_hints_leave_sdk_defaults_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEMAPACT_DATABRICKS_WORKSPACE_URL", raising=False)
    monkeypatch.delenv("SEMAPACT_DATABRICKS_TOKEN", raising=False)
    monkeypatch.delenv("SEMAPACT_DATABRICKS_PROFILE", raising=False)
    monkeypatch.setattr(
        "semapact.platforms.databricks.configuration.config_manager.get",
        lambda key, default=None: default,
    )

    hints = resolve_databricks_connection_hints()

    assert hints.workspace_url is None
    assert hints.token is None
    assert hints.profile is None


def test_invalid_databricks_config_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "semapact.platforms.databricks.configuration.config_manager.get",
        lambda key, default=None: {"unknown": "value"} if key == "databricks" else default,
    )

    with pytest.raises(ValidationError, match="Invalid databricks configuration"):
        resolve_databricks_connection_hints()
