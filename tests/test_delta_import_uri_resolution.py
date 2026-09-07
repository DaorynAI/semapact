from __future__ import annotations

import argparse
from types import SimpleNamespace
from typing import Any

import semapact.importers.delta_importer as delta_importer
from semapact.interfaces.commands import import_cmd, plan_cmd
from semapact.interfaces.commands.utils import _split_discovered_delta_tables


def test_resolve_table_uris_deduplicates_direct_source() -> None:
    uri = "abfss://container@account.dfs.core.windows.net/product/orders"

    assert delta_importer._resolve_table_uris(  # noqa: SLF001
        uri,
        {"table_uris": [uri]},
    ) == [uri]


def test_resolve_table_uris_deduplicates_normalized_and_repeated_entries() -> None:
    source = "abfss://container@account.dfs.core.windows.net/product/orders/"
    orders = source.rstrip("/")
    payments = "abfss://container@account.dfs.core.windows.net/product/payments"

    assert delta_importer._resolve_table_uris(  # noqa: SLF001
        source,
        {"table_uris": [orders, payments, f"{payments}/", payments]},
    ) == [source, payments]


def test_resolve_table_uris_preserves_distinct_additional_tables() -> None:
    source = "s3://lake/silver/orders"
    payments = "s3://lake/silver/payments"

    assert delta_importer._resolve_table_uris(  # noqa: SLF001
        source,
        {"table_uris": [payments]},
    ) == [source, payments]


def test_split_discovered_delta_tables_uses_discovered_table_as_primary() -> None:
    discovery_root = "s3://lake/silver"
    orders = "s3://lake/silver/orders"
    payments = "s3://lake/silver/payments"

    assert _split_discovered_delta_tables(
        discovery_root,
        [orders, payments],
    ) == (orders, [payments])
    assert _split_discovered_delta_tables(orders, [orders]) == (orders, [])


def test_import_command_does_not_inject_discovery_root(
    sample_odcs_model: Any,
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    (tmp_path / "orders" / "_delta_log").mkdir(parents=True)
    (tmp_path / "payments" / "_delta_log").mkdir(parents=True)

    captured: dict[str, Any] = {}

    def _fake_import_from_source(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return sample_odcs_model.model_copy(deep=True)

    monkeypatch.setattr(
        "datacontract.data_contract.DataContract.import_from_source",
        _fake_import_from_source,
    )
    monkeypatch.setattr(
        import_cmd.PluginRegistry,
        "execute_hook",
        lambda *_args, **_kwargs: None,
    )

    args = argparse.Namespace(
        runtime_context="auto",
        existing=None,
        format="delta",
        source=str(tmp_path),
        tables=None,
        output=tmp_path / "out.yaml",
        effective_date=None,
        workspace_url=None,
        token=None,
        sql_http_path=None,
        extract_lineage=False,
    )

    import_cmd.run_import(args)

    expected_tables = {
        str((tmp_path / "orders").absolute()),
        str((tmp_path / "payments").absolute()),
    }
    assert captured["source"] != str(tmp_path)
    assert {captured["source"], *captured["table_uris"]} == expected_tables
    assert len(captured["table_uris"]) == 1


def test_plan_command_does_not_inject_discovery_root(
    sample_odcs_model: Any,
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    (tmp_path / "orders" / "_delta_log").mkdir(parents=True)
    (tmp_path / "payments" / "_delta_log").mkdir(parents=True)

    captured: dict[str, Any] = {}

    class FakeLoader:
        def load(self, _path: str) -> Any:
            return sample_odcs_model.model_copy(deep=True)

    class FakePipeline:
        def __init__(self) -> None:
            self.loader = FakeLoader()

        def import_schema(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return sample_odcs_model.model_copy(deep=True)

        def merge_contract_updates(self, *_args: Any, **_kwargs: Any) -> Any:
            return SimpleNamespace(
                contract=sample_odcs_model.model_copy(deep=True),
                conflicts=[],
            )

    monkeypatch.setattr(
        "semapact.orchestrator.pipeline.ContractPipeline",
        FakePipeline,
    )
    monkeypatch.setattr(
        plan_cmd,
        "evaluate_governance_decision",
        lambda *_args, **_kwargs: SimpleNamespace(
            evidence=SimpleNamespace(has_changes=False),
        ),
    )
    monkeypatch.setattr(
        plan_cmd,
        "evaluate_governance_gate",
        lambda *_args, **_kwargs: SimpleNamespace(reason="allowed"),
    )

    args = argparse.Namespace(
        effective_date="2026-09-07",
        base="base.yaml",
        type="delta",
        source=str(tmp_path),
        tables=None,
        workspace_url=None,
        token=None,
    )

    plan_cmd.run_plan(args)

    expected_tables = {
        str((tmp_path / "orders").absolute()),
        str((tmp_path / "payments").absolute()),
    }
    import_args = captured["import_args"]
    assert captured["source"] != str(tmp_path)
    assert {captured["source"], *import_args["table_uris"]} == expected_tables
    assert len(import_args["table_uris"]) == 1
