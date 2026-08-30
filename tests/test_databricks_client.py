from __future__ import annotations

import pytest

from semapact.platforms.databricks import client as databricks_client
from semapact.platforms.databricks.client import create_databricks_workspace_client


class _FakeWorkspaceClient:
    def __init__(self, **kwargs: str) -> None:
        self.kwargs = kwargs


def test_create_databricks_workspace_client_uses_explicit_pat_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        databricks_client,
        "_load_workspace_client_class",
        lambda: _FakeWorkspaceClient,
    )

    client = create_databricks_workspace_client(
        workspace_url=" https://adb.example/ ",
        token="secret-token",
    )

    assert isinstance(client, _FakeWorkspaceClient)
    assert client.kwargs == {
        "host": "https://adb.example",
        "token": "secret-token",
        "auth_type": "pat",
    }


@pytest.mark.parametrize(
    ("workspace_url", "token", "message"),
    [
        ("", "secret-token", "workspace_url is required"),
        ("   ", "secret-token", "workspace_url is required"),
        ("https://adb.example", "", "token is required"),
        ("https://adb.example", "   ", "token is required"),
    ],
)
def test_missing_credentials_fail_without_echoing_secret_values(
    workspace_url: str,
    token: str,
    message: str,
) -> None:
    with pytest.raises(ValueError) as exc_info:
        create_databricks_workspace_client(
            workspace_url=workspace_url,
            token=token,
        )

    assert str(exc_info.value) == message
    assert "secret-token" not in str(exc_info.value)


def test_workspace_client_factory_is_loaded_only_after_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = False

    def _load() -> type[_FakeWorkspaceClient]:
        nonlocal loaded
        loaded = True
        return _FakeWorkspaceClient

    monkeypatch.setattr(databricks_client, "_load_workspace_client_class", _load)

    with pytest.raises(ValueError, match="workspace_url is required"):
        create_databricks_workspace_client(workspace_url="", token="secret-token")

    assert loaded is False
