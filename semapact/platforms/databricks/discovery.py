"""Read-only Databricks table discovery.

Discovery answers which assets exist in a Unity Catalog schema. It does not
observe table structure, create an ODCS contract, evaluate governance, or
resolve authentication. Callers supply an initialized ``WorkspaceClient``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient


class _TableInfoLike(Protocol):
    full_name: str | None
    name: str | None


class _TablesApiLike(Protocol):
    def list(
        self,
        *,
        catalog_name: str,
        schema_name: str,
    ) -> Iterable[_TableInfoLike]: ...


class _WorkspaceClientLike(Protocol):
    tables: _TablesApiLike


def discover_databricks_tables(
    *,
    client: WorkspaceClient | _WorkspaceClientLike,
    catalog_name: str,
    schema_name: str,
) -> tuple[str, ...]:
    """Return stable fully qualified names for tables visible in one UC schema."""
    catalog = _required_name(catalog_name, field="catalog_name")
    schema = _required_name(schema_name, field="schema_name")

    discovered: set[str] = set()
    for table in client.tables.list(catalog_name=catalog, schema_name=schema):
        full_name = _text(table.full_name)
        if not full_name:
            name = _text(table.name)
            if not name:
                raise ValueError("Databricks discovery returned a table without an identity")
            full_name = f"{catalog}.{schema}.{name}"
        discovered.add(full_name)

    return tuple(sorted(discovered, key=lambda value: (value.casefold(), value)))


def _required_name(value: str, *, field: str) -> str:
    cleaned = _text(value)
    if not cleaned:
        raise ValueError(f"{field} is required for Databricks discovery")
    return cleaned


def _text(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
