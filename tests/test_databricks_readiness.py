from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from semapact.application.models.readiness import ReadinessStatus
from semapact.platforms.databricks import readiness
from semapact.platforms.databricks.readiness import DatabricksReadinessProbe


class _CurrentUser:
    def __init__(self) -> None:
        self.calls = 0

    def me(self):
        self.calls += 1
        return SimpleNamespace(user_name="svc-semapact@example.com")


class _Schemas:
    def __init__(self) -> None:
        self.full_names: list[str] = []

    def get(self, *, full_name: str):
        self.full_names.append(full_name)
        return SimpleNamespace(full_name=full_name)


class _StatementExecution:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def execute_statement(self, *, statement: str, warehouse_id: str, wait_timeout: str):
        self.calls.append((statement, warehouse_id, wait_timeout))
        return SimpleNamespace(
            statement_id="stmt-1",
            status=SimpleNamespace(state="SUCCEEDED"),
        )

    def get_statement(self, statement_id: str):
        raise AssertionError(f"unexpected poll for {statement_id}")


class _Client:
    def __init__(self) -> None:
        self.config = SimpleNamespace(host="https://workspace.example")
        self.current_user = _CurrentUser()
        self.schemas = _Schemas()
        self.statement_execution = _StatementExecution()


def test_databricks_probe_checks_identity_uc_and_read_only_statement_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client()
    monkeypatch.setattr(
        readiness,
        "create_configured_databricks_workspace_client",
        lambda **kwargs: client,
    )

    checks = DatabricksReadinessProbe(
        runtime_target="main.sales",
        workspace_url="https://workspace.example",
        warehouse_id="warehouse-123",
        poll_interval_seconds=0,
    ).run()

    assert [check.status for check in checks] == [
        ReadinessStatus.PASS,
        ReadinessStatus.PASS,
        ReadinessStatus.PASS,
        ReadinessStatus.PASS,
    ]
    assert client.current_user.calls == 1
    assert client.schemas.full_names == ["main.sales"]
    assert client.statement_execution.calls == [
        ("SELECT 1", "warehouse-123", "10s")
    ]


def test_missing_warehouse_blocks_deployment_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client()
    monkeypatch.setattr(
        readiness,
        "create_configured_databricks_workspace_client",
        lambda **kwargs: client,
    )

    checks = DatabricksReadinessProbe(
        runtime_target="main.sales",
        warehouse_id=None,
    ).run()

    statement_check = next(
        check
        for check in checks
        if check.check_id == "databricks.statement_execution"
    )
    assert statement_check.status is ReadinessStatus.FAIL
    assert statement_check.required is True
    assert client.statement_execution.calls == []


def test_client_initialization_failure_does_not_leak_exception_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(**kwargs):
        raise RuntimeError("token=secret-token")

    monkeypatch.setattr(
        readiness,
        "create_configured_databricks_workspace_client",
        _raise,
    )

    checks = DatabricksReadinessProbe(
        runtime_target="main.sales",
        warehouse_id="warehouse-123",
    ).run()
    rendered = json.dumps(
        [check.model_dump(mode="json") for check in checks],
        sort_keys=True,
    )

    assert checks[0].status is ReadinessStatus.FAIL
    assert checks[0].error_type == "RuntimeError"
    assert "secret-token" not in rendered


def test_uc_permission_failure_is_reported_without_exposing_provider_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client()

    def _deny(*, full_name: str):
        raise PermissionError("bearer secret-token")

    client.schemas.get = _deny
    monkeypatch.setattr(
        readiness,
        "create_configured_databricks_workspace_client",
        lambda **kwargs: client,
    )

    checks = DatabricksReadinessProbe(
        runtime_target="main.sales",
        warehouse_id="warehouse-123",
        poll_interval_seconds=0,
    ).run()
    uc_check = next(
        check for check in checks if check.check_id == "databricks.unity_catalog"
    )

    assert uc_check.status is ReadinessStatus.FAIL
    assert uc_check.error_type == "PermissionError"
    assert "secret-token" not in json.dumps(uc_check.model_dump(mode="json"))
