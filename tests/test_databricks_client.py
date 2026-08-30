from __future__ import annotations

import pytest

from semapact.platforms.databricks import client as databricks_client
from semapact.platforms.databricks.client import create_databricks_workspace_client


class _FakeWorkspaceClient:
    def __init__(self, **kwargs: str) -> None:
        self.kwargs = kwargs


def _use_fake_workspace_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        databricks_client,
        "_load_workspace_client_class",
        lambda: _FakeWorkspaceClient,
    )


def test_create_databricks_workspace_client_forwards_available_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_fake_workspace_client(monkeypatch)

    client = create_databricks_workspace_client(
        workspace_url=" https://adb.example/ ",
        token="secret-token",
        profile=" prod ",
    )

    assert isinstance(client, _FakeWorkspaceClient)
    assert client.kwargs == {
        "host": "https://adb.example",
        "token": "secret-token",
        "profile": "prod",
    }


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, {}),
        ({"workspace_url": "https://adb.example/"}, {"host": "https://adb.example"}),
        ({"token": "secret-token"}, {"token": "secret-token"}),
        ({"profile": "prod"}, {"profile": "prod"}),
    ],
)
def test_create_databricks_workspace_client_leaves_missing_auth_to_sdk(
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, str],
    expected: dict[str, str],
) -> None:
    _use_fake_workspace_client(monkeypatch)

    client = create_databricks_workspace_client(**kwargs)

    assert isinstance(client, _FakeWorkspaceClient)
    assert client.kwargs == expected


def test_create_databricks_workspace_client_omits_blank_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_fake_workspace_client(monkeypatch)

    client = create_databricks_workspace_client(
        workspace_url="   ",
        token="   ",
        profile="   ",
    )

    assert isinstance(client, _FakeWorkspaceClient)
    assert client.kwargs == {}
