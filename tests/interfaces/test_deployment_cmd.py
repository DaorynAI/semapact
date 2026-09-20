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


def test_deployment_parser_exposes_candidate_and_finalized_release_modes() -> None:
    parser = cli._build_parser()

    candidate = parser.parse_args(
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
            "development",
            "--bundle-out",
            "candidate.bundle.json",
            "--output",
            "json",
        ]
    )
    release = parser.parse_args(
        [
            "deployment",
            "assess",
            "--release-id",
            "release-1",
            "--server",
            "production",
            "--bundle-out",
            "release.bundle.json",
        ]
    )
    deploy = parser.parse_args(
        [
            "deployment",
            "deploy",
            "--bundle",
            "bundle.json",
            "--warehouse-id",
            "warehouse-1",
            "--operational-history",
            "sqlite:///history.db",
            "--output",
            "json",
        ]
    )

    assert candidate.deployment_command == "assess"
    assert candidate.release_id is None
    assert candidate.server == "development"
    assert candidate.bundle_out == "candidate.bundle.json"

    assert release.deployment_command == "assess"
    assert release.release_id == "release-1"
    assert release.repository_root == "."
    assert release.server == "production"

    assert deploy.deployment_command == "deploy"
    assert deploy.bundle == "bundle.json"
    assert deploy.warehouse_id == "warehouse-1"
    assert deploy.operational_history == "sqlite:///history.db"
    assert deploy.output == "json"


@pytest.mark.parametrize(
    "legacy_args",
    [
        ["deployment", "plan"],
        ["deployment", "preview"],
        ["deployment", "execute"],
        ["deployment", "verify"],
        ["deployment", "approve"],
        ["deployment", "assess", "--release"],
    ],
)
def test_legacy_deployment_cli_surfaces_are_not_public(legacy_args) -> None:
    parser = cli._build_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(legacy_args)

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


def test_candidate_assessment_requires_candidate_arguments() -> None:
    args = type(
        "Args",
        (),
        {
            "base": None,
            "candidate": None,
            "base_revision_ref": None,
            "candidate_revision_ref": None,
            "effective_date": None,
        },
    )()

    with pytest.raises(ValidationError, match="Candidate deployment assessment"):
        deployment_cmd._require_candidate_args(args)


def test_release_assessment_rejects_candidate_arguments() -> None:
    args = type(
        "Args",
        (),
        {
            "base": "base.yaml",
            "candidate": None,
            "base_revision_ref": None,
            "candidate_revision_ref": None,
            "effective_date": None,
        },
    )()

    with pytest.raises(ValidationError, match="cannot be combined"):
        deployment_cmd._reject_candidate_args_for_release(args)


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


def test_operational_history_cli_override_takes_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from semapact.core.config import config_manager

    monkeypatch.setattr(
        config_manager,
        "get",
        lambda *args, **kwargs: {
            "backend": "sqlite",
            "path": ".semapact/from-config.db",
        },
    )

    assert (
        deployment_cmd._resolve_operational_history_uri(
            "sqlite:///explicit.db"
        )
        == "sqlite:///explicit.db"
    )


def test_operational_history_falls_back_to_typed_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from semapact.core.config import config_manager

    monkeypatch.setattr(
        config_manager,
        "get",
        lambda *args, **kwargs: {
            "backend": "sqlite",
            "path": ".semapact/operational.db",
        },
    )

    assert (
        deployment_cmd._resolve_operational_history_uri(None)
        == "sqlite:///.semapact/operational.db"
    )


def test_invalid_operational_history_config_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from semapact.core.config import config_manager

    monkeypatch.setattr(
        config_manager,
        "get",
        lambda *args, **kwargs: {
            "backend": "git",
            "path": ".semapact/history",
        },
    )

    with pytest.raises(ValidationError, match="history.operational"):
        deployment_cmd._resolve_operational_history_uri(None)
