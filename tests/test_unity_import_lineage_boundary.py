from __future__ import annotations

import inspect

import pytest

from semapact.importers import unity_importer
from semapact.importers.unity_importer import import_unity_contract


def test_unity_import_rejects_lineage_projection() -> None:
    with pytest.raises(ValueError, match="runtime observation evidence"):
        import_unity_contract(
            table_fqn="main.silver.orders",
            workspace_url="https://adb.example",
            token="token",
            sql_http_path="/sql/1.0/warehouses/example",
            extract_lineage=True,
        )


def test_unity_importer_has_no_lineage_mutation_dependency() -> None:
    source = inspect.getsource(unity_importer)

    assert "semapact.importers.unity_lineage" not in source
    assert "enrich_unity_lineage" not in source
    assert "transformSourceObjects" not in source
    assert "transformLogic" not in source
