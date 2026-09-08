from __future__ import annotations

from types import SimpleNamespace

import pytest

from semapact.exceptions import ValidationError
from semapact.reconciliation import ReconciliationResult, RuntimeDriftStatus
from semapact.services import reconciliation_service
from semapact.services.reconciliation_service import ReconciliationService


def _result() -> ReconciliationResult:
    return ReconciliationResult(
        contract_id="orders-contract",
        contract_version="1.2.3",
        observation_source_identifier="https://adb.example",
        observation_fingerprint="obs-v1:sha256:test",
    )


def _single_schema_contract() -> SimpleNamespace:
    return SimpleNamespace(schema_=[object()])


def test_reconciliation_service_delegates_existing_m1_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}
    contract = _single_schema_contract()
    observation = object()
    client = SimpleNamespace(config=SimpleNamespace(host="https://adb.example/"))
    result = _result()

    class _Loader:
        def __init__(self, runtime_context: str) -> None:
            calls["runtime_context"] = runtime_context

        def load(self, contract_path: str) -> object:
            calls["contract_path"] = contract_path
            return contract

    def _create_client(**kwargs: str | None) -> object:
        calls["client_kwargs"] = kwargs
        return client

    def _observe(**kwargs: object) -> object:
        calls["observe_kwargs"] = kwargs
        return observation

    def _reconcile(base: object, observed: object) -> ReconciliationResult:
        calls["reconcile_args"] = (base, observed)
        return result

    def _classify(value: ReconciliationResult) -> RuntimeDriftStatus:
        calls["classify_arg"] = value
        return RuntimeDriftStatus.DRIFT

    monkeypatch.setattr(reconciliation_service, "ContractLoader", _Loader)
    monkeypatch.setattr(
        reconciliation_service, "create_databricks_workspace_client", _create_client
    )
    monkeypatch.setattr(reconciliation_service, "observe_databricks_table", _observe)
    monkeypatch.setattr(reconciliation_service, "reconcile_governed_contract", _reconcile)
    monkeypatch.setattr(
        reconciliation_service, "classify_reconciliation_status", _classify
    )

    analysis = ReconciliationService().reconcile_databricks_table(
        contract_path="contracts/orders.yaml",
        table_fqn="main.sales.orders",
        workspace_url="https://adb.example",
        token="secret",
        profile="prod",
        runtime_context="auto",
    )

    assert calls["runtime_context"] == "auto"
    assert calls["contract_path"] == "contracts/orders.yaml"
    assert calls["client_kwargs"] == {
        "workspace_url": "https://adb.example",
        "token": "secret",
        "profile": "prod",
    }
    assert calls["observe_kwargs"] == {
        "client": client,
        "table_fqn": "main.sales.orders",
        "source_identifier": "https://adb.example",
    }
    assert calls["reconcile_args"] == (contract, observation)
    assert calls["classify_arg"] is result
    assert analysis.runtime_target == "main.sales.orders"
    assert analysis.result is result
    assert analysis.status is RuntimeDriftStatus.DRIFT


def test_reconciliation_service_rejects_multi_schema_contract_before_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Loader:
        def __init__(self, runtime_context: str) -> None:
            pass

        def load(self, contract_path: str) -> SimpleNamespace:
            return SimpleNamespace(schema_=[object(), object()])

    client_called = False

    def _create_client(**kwargs: str | None) -> object:
        nonlocal client_called
        client_called = True
        return object()

    monkeypatch.setattr(reconciliation_service, "ContractLoader", _Loader)
    monkeypatch.setattr(
        reconciliation_service, "create_databricks_workspace_client", _create_client
    )

    with pytest.raises(
        ValidationError,
        match="Single-table reconciliation currently requires exactly one governed schema",
    ):
        ReconciliationService().reconcile_databricks_table(
            contract_path="contracts/orders.yaml",
            table_fqn="main.sales.orders",
        )

    assert client_called is False


def test_reconciliation_service_requires_sdk_resolved_workspace_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Loader:
        def __init__(self, runtime_context: str) -> None:
            pass

        def load(self, contract_path: str) -> SimpleNamespace:
            return _single_schema_contract()

    monkeypatch.setattr(reconciliation_service, "ContractLoader", _Loader)
    monkeypatch.setattr(
        reconciliation_service,
        "create_databricks_workspace_client",
        lambda **kwargs: SimpleNamespace(config=SimpleNamespace(host=None)),
    )

    with pytest.raises(
        RuntimeError,
        match="Databricks WorkspaceClient did not resolve a workspace host",
    ):
        ReconciliationService().reconcile_databricks_table(
            contract_path="contracts/orders.yaml",
            table_fqn="main.sales.orders",
        )
