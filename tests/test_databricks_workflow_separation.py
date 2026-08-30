from __future__ import annotations

from semapact.importers import unity_importer


def test_unity_contract_import_remains_independently_callable(monkeypatch) -> None:
    imported_contract = object()
    calls: list[dict[str, object]] = []

    class _FakeDataContract:
        @staticmethod
        def import_from_source(**kwargs: object) -> object:
            calls.append(kwargs)
            return imported_contract

    from semapact.core.config import config_manager

    monkeypatch.setattr(unity_importer, "DataContract", _FakeDataContract)
    monkeypatch.setattr(config_manager, "get", lambda _key: None)
    monkeypatch.setattr(
        unity_importer,
        "enrich_unity_contract_relationships",
        lambda contract, **_kwargs: contract,
    )

    result = unity_importer.import_unity_contract(
        table_fqn="main.sales.orders",
        workspace_url="https://adb.example",
        token="secret-token",
    )

    assert result is imported_contract
    assert calls == [
        {
            "format": "unity",
            "source": None,
            "unity_table_full_name": ["main.sales.orders"],
        }
    ]


def test_unity_contract_import_does_not_depend_on_observation_or_discovery() -> None:
    from pathlib import Path

    source = Path("semapact/importers/unity_importer.py").read_text(encoding="utf-8")

    assert "semapact.observation" not in source
    assert "semapact.platforms.databricks.discovery" not in source
