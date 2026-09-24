from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.importers.unity_importer import import_unity_contract
from semapact.platforms.databricks.configuration import DatabricksConnectionHints


@dataclass
class _TableInfo:
    full_name: str
    table_type: str = "MANAGED"

    @property
    def name(self) -> str:
        return self.full_name.split(".")[-1]

    def as_dict(self) -> dict[str, object]:
        return {
            "full_name": self.full_name,
            "name": self.name,
            "table_type": self.table_type,
            "table_constraints": [],
        }


class _Tables:
    def __init__(self, tables: list[_TableInfo]) -> None:
        self._tables = {table.full_name: table for table in tables}
        self.get_calls: list[str] = []

    def list(self, *, catalog_name: str, schema_name: str):
        prefix = f"{catalog_name}.{schema_name}."
        return [
            table
            for name, table in self._tables.items()
            if name.startswith(prefix)
        ]

    def get(self, full_name: str):
        self.get_calls.append(full_name)
        return self._tables[full_name]


class _Client:
    def __init__(self, tables: list[_TableInfo]) -> None:
        self.tables = _Tables(tables)
        self.config = SimpleNamespace(host="https://adb.example")


def _install_mapper(monkeypatch: pytest.MonkeyPatch) -> None:
    def create_odcs():
        return OpenDataContractStandard(
            apiVersion="v3.1.0",
            kind="DataContract",
            id="imported",
            name="Imported",
            version="1.0.0",
            status="draft",
            schema=[],
        )

    def convert_unity_schema(contract, table_info):  # noqa: ANN001
        contract.schema_ = list(contract.schema_ or [])
        contract.schema_.append(
            SchemaObject(
                name=table_info.name,
                physicalName=table_info.name,
                physicalType="table",
                properties=[
                    SchemaProperty(
                        name="id",
                        physicalName="id",
                        logicalType="integer",
                        physicalType="BIGINT",
                        required=True,
                    )
                ],
            )
        )
        return contract

    monkeypatch.setattr(
        "datacontract.imports.unity_importer.create_odcs",
        create_odcs,
    )
    monkeypatch.setattr(
        "datacontract.imports.unity_importer.convert_unity_schema",
        convert_unity_schema,
    )


def test_schema_level_import_builds_one_data_product_from_all_discovered_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_mapper(monkeypatch)
    client = _Client(
        [
            _TableInfo("main.gold.orders", "MANAGED"),
            _TableInfo("main.gold.customer_view", "VIEW"),
        ]
    )

    contract = import_unity_contract(
        table_fqn="main.gold",
        client=client,
    )

    assert contract.id == "main-gold-product"
    assert contract.status == "active"
    assert [schema.name for schema in contract.schema_ or []] == [
        "customer_view",
        "orders",
    ]
    assert client.tables.get_calls == [
        "main.gold.customer_view",
        "main.gold.orders",
    ]


def test_table_level_import_fetches_only_requested_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_mapper(monkeypatch)
    client = _Client(
        [
            _TableInfo("main.gold.orders"),
            _TableInfo("main.gold.customers"),
        ]
    )

    contract = import_unity_contract(
        table_fqn="main.gold.orders",
        client=client,
    )

    assert [schema.name for schema in contract.schema_ or []] == ["orders"]
    assert client.tables.get_calls == ["main.gold.orders"]


def test_import_resolves_config_before_constructing_workspace_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_mapper(monkeypatch)
    client = _Client([_TableInfo("main.gold.orders")])
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "semapact.platforms.databricks.configuration.resolve_databricks_connection_hints",
        lambda **kwargs: DatabricksConnectionHints(
            workspace_url="https://config.example",
            token="config-token",
            profile="config-profile",
        ),
    )

    def fake_create_client(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return client

    monkeypatch.setattr(
        "semapact.platforms.databricks.client.create_databricks_workspace_client",
        fake_create_client,
    )

    import_unity_contract(table_fqn="main.gold.orders")

    assert captured == {
        "workspace_url": "https://config.example",
        "token": "config-token",
        "profile": "config-profile",
    }


@pytest.mark.parametrize(
    "source",
    [
        "",
        "main",
        "main.gold.orders.extra",
        "main..orders",
    ],
)
def test_import_rejects_ambiguous_unity_source(source: str) -> None:
    with pytest.raises(
        ValueError,
        match="catalog.schema or catalog.schema.table",
    ):
        import_unity_contract(table_fqn=source, client=_Client([]))
