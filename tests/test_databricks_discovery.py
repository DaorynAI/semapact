from __future__ import annotations

from dataclasses import dataclass

import pytest

from semapact.platforms.databricks.discovery import discover_databricks_tables


@dataclass
class _FakeTable:
    full_name: str | None
    name: str | None = None


class _FakeTablesApi:
    def __init__(self, tables: list[_FakeTable]) -> None:
        self._tables = tables
        self.calls: list[dict[str, str]] = []

    def list(self, *, catalog_name: str, schema_name: str) -> list[_FakeTable]:
        self.calls.append(
            {
                "catalog_name": catalog_name,
                "schema_name": schema_name,
            }
        )
        return self._tables


class _FakeWorkspaceClient:
    def __init__(self, tables: list[_FakeTable]) -> None:
        self.tables = _FakeTablesApi(tables)


def test_discover_databricks_tables_lists_without_observing_or_importing() -> None:
    client = _FakeWorkspaceClient(
        [
            _FakeTable("main.sales.Z_orders"),
            _FakeTable("main.sales.accounts"),
            _FakeTable("main.sales.accounts"),
            _FakeTable(None, name="customers"),
        ]
    )

    discovered = discover_databricks_tables(
        client=client,
        catalog_name=" main ",
        schema_name=" sales ",
    )

    assert discovered == (
        "main.sales.accounts",
        "main.sales.customers",
        "main.sales.Z_orders",
    )
    assert client.tables.calls == [
        {
            "catalog_name": "main",
            "schema_name": "sales",
        }
    ]


def test_discover_databricks_tables_fails_on_missing_table_identity() -> None:
    client = _FakeWorkspaceClient([_FakeTable(None)])

    with pytest.raises(
        ValueError,
        match="Databricks discovery returned a table without an identity",
    ):
        discover_databricks_tables(
            client=client,
            catalog_name="main",
            schema_name="sales",
        )


@pytest.mark.parametrize(
    ("catalog_name", "schema_name", "message"),
    [
        ("", "sales", "catalog_name is required for Databricks discovery"),
        ("   ", "sales", "catalog_name is required for Databricks discovery"),
        ("main", "", "schema_name is required for Databricks discovery"),
        ("main", "   ", "schema_name is required for Databricks discovery"),
    ],
)
def test_discover_databricks_tables_validates_scope_before_sdk_call(
    catalog_name: str,
    schema_name: str,
    message: str,
) -> None:
    client = _FakeWorkspaceClient([])

    with pytest.raises(ValueError, match=message):
        discover_databricks_tables(
            client=client,
            catalog_name=catalog_name,
            schema_name=schema_name,
        )

    assert client.tables.calls == []


def test_databricks_discovery_module_has_no_contract_or_governance_dependency() -> None:
    from pathlib import Path

    source = Path("semapact/platforms/databricks/discovery.py").read_text(
        encoding="utf-8"
    )

    forbidden = (
        "datacontract",
        "open_data_contract_standard",
        "semapact.importers",
        "semapact.observation",
        "semapact.lifecycle",
        "semapact.governance",
    )
    assert not any(name in source for name in forbidden)
