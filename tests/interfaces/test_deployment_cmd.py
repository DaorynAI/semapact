from __future__ import annotations

import sys

from open_data_contract_standard.model import Server
import pytest

from semapact.exceptions import ValidationError
from semapact.interfaces import cli
from semapact.interfaces.commands import deployment_cmd
from semapact.interfaces.commands.deployment_cmd import DeploymentCommandResult
from semapact.interfaces.outcomes import ProcessOutcome


SOURCE_REFERENCE = "https://workspace.example"


def test_deployment_parser_exposes_only_bundle_workflow() -> None:
    parser = cli._build_parser()

    assess = parser.parse_args(
        [
            "deployment",
            "assess",
            "--base",
            "base.yaml",
            "--candidate",
            "candidate.yaml",
            "--base-revision-ref",
            "git:base",
            "--candidate-revision-ref",
            "git:candidate",
            "--effective-date",
            "2026-09-20",
            "--server",
            "production",
            "--bundle-out",
            "bundle.json",
            "--output",
            "json",
        ]
    )
    approve = parser.parse_args(
        [
            "deployment",
            "approve",
            "--bundle",
            "bundle.json",
            "--actor-reference",
            "human:reviewer",
            "--recorded-at",
            "2026-09-20T10:00:00+10:00",
            "--approval-out",
            "approval.json",
            "--output",
            "json",
        ]
    )
    deploy = parser.parse_args(
        [
            "deployment",
            "deploy",
            "--bundle",
            "bundle.json",
            "--approval",
            "approval.json",
            "--warehouse-id",
            "warehouse-1",
            "--output",
            "json",
        ]
    )

    assert assess.deployment_command == "assess"
    assert assess.server == "production"
    assert assess.bundle_out == "bundle.json"
    assert assess.output == "json"

    assert approve.deployment_command == "approve"
    assert approve.bundle == "bundle.json"
    assert approve.actor_reference == "human:reviewer"
    assert approve.approval_out == "approval.json"

    assert deploy.deployment_command == "deploy"
    assert deploy.bundle == "bundle.json"
    assert deploy.approval == "approval.json"
    assert deploy.repository_root == "."
    assert deploy.warehouse_id == "warehouse-1"
    assert deploy.output == "json"


@pytest.mark.parametrize("legacy_command", ["plan", "preview", "execute", "verify"])
def test_legacy_deployment_commands_are_not_public_cli(
    legacy_command: str,
) -> None:
    parser = cli._build_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["deployment", legacy_command])

    assert exc.value.code == 2


@pytest.mark.parametrize(
    "outcome,expected_exit",
    [
        (ProcessOutcome.SUCCESS, 0),
        (ProcessOutcome.RUNTIME_DRIFT, 6),
        (ProcessOutcome.RUNTIME_INDETERMINATE, 7),
    ],
)
def test_main_preserves_bundle_deploy_outcome_semantics(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    outcome: ProcessOutcome,
    expected_exit: int,
) -> None:
    monkeypatch.setattr(
        deployment_cmd,
        "run_deployment_deploy",
        lambda args: DeploymentCommandResult(output="deployment", outcome=outcome),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["semapact", "deployment", "deploy", "--bundle", "bundle.json"],
    )

    assert cli.main() == expected_exit
    assert capsys.readouterr().out.strip() == "deployment"


def test_assessment_source_reference_prefers_contract_server_host() -> None:
    server = Server.model_validate(
        {
            "server": "production",
            "type": "databricks",
            "host": SOURCE_REFERENCE,
            "catalog": "main",
            "schema": "silver",
        }
    )

    assert (
        deployment_cmd._assessment_source_reference(server, None)
        == SOURCE_REFERENCE
    )


def test_assessment_source_reference_requires_cli_fallback_without_server() -> None:
    assert (
        deployment_cmd._assessment_source_reference(None, SOURCE_REFERENCE)
        == SOURCE_REFERENCE
    )

    with pytest.raises(ValidationError, match="provide --source-reference"):
        deployment_cmd._assessment_source_reference(None, None)


def test_assessment_source_reference_cannot_override_contract_host() -> None:
    server = Server.model_validate(
        {
            "server": "production",
            "type": "databricks",
            "host": SOURCE_REFERENCE,
            "catalog": "main",
            "schema": "silver",
        }
    )

    with pytest.raises(ValidationError, match="cannot override"):
        deployment_cmd._assessment_source_reference(
            server,
            "https://other-workspace.example",
        )
