from __future__ import annotations

from types import SimpleNamespace

import pytest

from semapact.platforms.databricks.configuration import DatabricksConnectionHints
from semapact.platforms.runtime_registry import _create_databricks_client_and_provider


def test_runtime_registry_resolves_semapact_databricks_hints_before_client_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    hints = DatabricksConnectionHints(
        workspace_url="https://config.example",
        token="config-token",
        profile="config-profile",
    )
    client = SimpleNamespace(config=SimpleNamespace(host="https://config.example"))

    monkeypatch.setattr(
        "semapact.platforms.databricks.configuration.resolve_databricks_connection_hints",
        lambda **kwargs: hints,
    )

    def fake_create_client(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return client

    monkeypatch.setattr(
        "semapact.platforms.databricks.create_databricks_workspace_client",
        fake_create_client,
    )
    monkeypatch.setattr(
        "semapact.platforms.databricks.DatabricksRuntimeProvider",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )

    resolved_client, provider = _create_databricks_client_and_provider()

    assert resolved_client is client
    assert captured == {
        "workspace_url": "https://config.example",
        "token": "config-token",
        "profile": "config-profile",
    }
    assert provider.client is client
    assert provider.source_identifier == "https://config.example"
