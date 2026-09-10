from __future__ import annotations

import json
import sys

from open_data_contract_standard.model import OpenDataContractStandard, SchemaObject, SchemaProperty
import pytest

from semapact.contractops import AppliedContractRelease
from semapact.exceptions import ValidationError
from semapact.interfaces import cli
from semapact.interfaces.commands import deployment_cmd
from semapact.interfaces.commands.deployment_cmd import DeploymentCommandResult
from semapact.interfaces.outcomes import ProcessOutcome


def _release() -> AppliedContractRelease:
    contract = OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="orders-product",
        name="Orders",
        version="1.2.0",
        status="active",
        schema=[
            SchemaObject(
                name="orders",
                physicalName="orders_runtime",
                properties=[
                    SchemaProperty(
                        name="id",
                        physicalName="order_id",
                        type="integer",
                        physicalType="BIGINT",
                        required=True,
                    )
                ],
            )
        ],
    )
    return AppliedContractRelease(
        applied_release_id="applied-release:test",
        contract_id="orders-product",
        decision_id="decision:test",
        change_set_id="change-set:test",
        release_plan_id="release-plan:test",
        version_resolution_id="version-resolution:test",
        release_revision_ref="rev:released",
        selected_version="1.2.0",
        authorization_id="authorization:test",
        released_contract_json=json.dumps(
            contract.model_dump(mode="json", by_alias=True, exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


def test_deployment_parser_exposes_four_explicit_phases() -> None:
    parser = cli._build_parser()

    plan = parser.parse_args(
        [
            "deployment",
            "plan",
            "--release",
            "release.json",
            "--platform",
            "databricks",
            "--runtime",
            "main.silver",
        ]
    )
    preview = parser.parse_args(
        ["deployment", "preview", "--plan", "plan.json"]
    )
    execute = parser.parse_args(
        [
            "deployment",
            "execute",
            "--plan",
            "plan.json",
            "--preview",
            "preview.json",
            "--authorization",
            "authorization.json",
            "--warehouse-id",
            "warehouse-1",
        ]
    )
    verify = parser.parse_args(
        ["deployment", "verify", "--plan", "plan.json", "--output", "json"]
    )

    assert plan.deployment_command == "plan"
    assert preview.deployment_command == "preview"
    assert not hasattr(preview, "warehouse_id")
    assert execute.deployment_command == "execute"
    assert execute.warehouse_id == "warehouse-1"
    assert verify.deployment_command == "verify"
    assert verify.output == "json"


def test_plan_command_outputs_canonical_deployment_plan(tmp_path) -> None:
    release_path = tmp_path / "release.json"
    release_path.write_text(_release().model_dump_json(), encoding="utf-8")
    args = cli._build_parser().parse_args(
        [
            "deployment",
            "plan",
            "--release",
            str(release_path),
            "--platform",
            "databricks",
            "--runtime",
            "main.silver",
            "--server",
            "production",
        ]
    )

    result = deployment_cmd.run_deployment_plan(args)
    payload = json.loads(result.output)

    assert result.outcome is ProcessOutcome.SUCCESS
    assert payload["applied_release_id"] == "applied-release:test"
    assert payload["target"] == {
        "platform": "databricks",
        "runtime_target": "main.silver",
        "server_name": "production",
    }
    assert payload["actions"][0]["governed_asset"] == "orders"
    assert payload["actions"][0]["physical_name"] == "orders_runtime"


def test_invalid_artifact_is_a_validation_failure(tmp_path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")

    with pytest.raises(ValidationError, match="Invalid DeploymentPlan artifact"):
        deployment_cmd._load_model(str(invalid), deployment_cmd.DeploymentPlan)


@pytest.mark.parametrize(
    "outcome,expected_exit",
    [
        (ProcessOutcome.SUCCESS, 0),
        (ProcessOutcome.RUNTIME_DRIFT, 6),
        (ProcessOutcome.RUNTIME_INDETERMINATE, 7),
    ],
)
def test_main_preserves_verification_outcome_semantics(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    outcome: ProcessOutcome,
    expected_exit: int,
) -> None:
    monkeypatch.setattr(
        deployment_cmd,
        "run_deployment_verify",
        lambda args: DeploymentCommandResult(output="verification", outcome=outcome),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["semapact", "deployment", "verify", "--plan", "plan.json"],
    )

    assert cli.main() == expected_exit
    assert capsys.readouterr().out.strip() == "verification"
