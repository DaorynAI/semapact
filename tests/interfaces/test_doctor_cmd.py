from __future__ import annotations

import json
import sys

from open_data_contract_standard.model import OpenDataContractStandard, Server
import pytest

from semapact.application.models.readiness import (
    ReadinessCheck,
    ReadinessStatus,
)
from semapact.interfaces import cli
from semapact.interfaces.commands import doctor_cmd
from semapact.interfaces.commands.doctor_cmd import DoctorCommandResult
from semapact.interfaces.outcomes import ProcessOutcome


def _contract() -> OpenDataContractStandard:
    server = Server.model_validate(
        {
            "server": "production",
            "type": "databricks",
            "host": "https://workspace.example",
            "catalog": "main",
            "schema": "sales",
        }
    )
    return OpenDataContractStandard.model_construct(
        id="sales-product",
        version="1.0.0",
        servers=[server],
        schema_=[],
    )


class _PassingProbe:
    key = "databricks"

    def run(self) -> tuple[ReadinessCheck, ...]:
        return (
            ReadinessCheck(
                check_id="databricks.configuration",
                status=ReadinessStatus.PASS,
                required=True,
                summary="Databricks configuration is ready.",
            ),
        )


def test_doctor_parser_is_contract_first_and_does_not_accept_credentials() -> None:
    args = cli._build_parser().parse_args(
        [
            "doctor",
            "--contract",
            "contracts/sales.yaml",
            "--warehouse-id",
            "warehouse-123",
            "--output",
            "json",
        ]
    )

    assert args.command == "doctor"
    assert args.contract == "contracts/sales.yaml"
    assert args.server is None
    assert args.platform is None
    assert args.runtime is None
    assert args.warehouse_id == "warehouse-123"
    assert args.output == "json"
    assert not hasattr(args, "token")
    assert not hasattr(args, "workspace_url")


def test_doctor_uses_contract_runtime_and_returns_machine_readable_report(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import semapact.platforms.runtime_registry as runtime_registry

    captured: dict[str, object] = {}

    def _create_probe(
        platform: str,
        *,
        runtime_target: str,
        contract_server=None,
        execution_config=None,
    ):
        captured.update(
            platform=platform,
            runtime_target=runtime_target,
            contract_server=contract_server,
            execution_config=execution_config,
        )
        return _PassingProbe()

    monkeypatch.setattr(doctor_cmd, "load_contract", lambda path: _contract())
    monkeypatch.setattr(
        runtime_registry,
        "create_runtime_readiness_probe",
        _create_probe,
    )

    args = cli._build_parser().parse_args(
        [
            "doctor",
            "--contract",
            "contracts/sales.yaml",
            "--warehouse-id",
            "warehouse-123",
            "--repository-root",
            str(tmp_path),
            "--output",
            "json",
        ]
    )
    result = doctor_cmd.run_doctor(args)
    payload = json.loads(result.output)

    assert result.outcome is ProcessOutcome.SUCCESS
    assert payload["ready"] is True
    assert payload["platform"] == "databricks"
    assert payload["runtime_target"] == "main.sales"
    assert captured["platform"] == "databricks"
    assert captured["runtime_target"] == "main.sales"
    assert getattr(captured["contract_server"], "server") == "production"
    assert getattr(captured["execution_config"], "warehouse_id") == "warehouse-123"
    assert any(
        check["check_id"] == "git.worktree"
        and check["status"] == "WARN"
        and check["required"] is False
        for check in payload["checks"]
    )


def test_main_maps_not_ready_to_validation_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        doctor_cmd,
        "run_doctor",
        lambda args: DoctorCommandResult(
            output="Readiness: NOT_READY",
            outcome=ProcessOutcome.VALIDATION_FAILED,
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["semapact", "doctor", "--contract", "contracts/sales.yaml"],
    )

    assert cli.main() == 2
    assert capsys.readouterr().out.strip() == "Readiness: NOT_READY"
