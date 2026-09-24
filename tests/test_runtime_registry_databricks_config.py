from __future__ import annotations

from types import SimpleNamespace

import pytest

from semapact.platforms.runtime_registry import _create_databricks_client_and_provider


def test_runtime_registry_uses_configured_databricks_client_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    client = SimpleNamespace(config=SimpleNamespace(host="https://config.example"))

    def fake_create_configured_client(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return client

    monkeypatch.setattr(
        "semapact.platforms.databricks.configuration.create_configured_databricks_workspace_client",
        fake_create_configured_client,
    )
    monkeypatch.setattr(
        "semapact.platforms.databricks.DatabricksRuntimeProvider",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )

    resolved_client, provider = _create_databricks_client_and_provider()

    assert resolved_client is client
    assert captured == {"workspace_url": None}
    assert provider.client is client
    assert provider.source_identifier == "https://config.example"
