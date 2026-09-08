from __future__ import annotations

import json
import sys

import pytest

from semapact.interfaces import cli
from semapact.interfaces.commands import reconcile_cmd
from semapact.interfaces.commands.reconcile_cmd import ReconcileCommandResult
from semapact.interfaces.outcomes import ProcessOutcome
from semapact.observation import ObservedAssetIdentity, RuntimeAssetBinding
from semapact.reconciliation import (
    ReconciliationDifference,
    ReconciliationDifferenceType,
    ReconciliationResult,
    ReconciliationSubject,
    RuntimeDriftStatus,
    RuntimeReasonCode,
)
from semapact.services.reconciliation_service import RuntimeReconciliation


def _analysis() -> RuntimeReconciliation:
    binding = RuntimeAssetBinding(
        governed_asset="orders",
        observed_asset=ObservedAssetIdentity(
            platform="warehouse",
            namespace=("analytics",),
            asset="fact_orders",
        ),
    )
    result = ReconciliationResult(
        contract_id="sales-product",
        contract_version="1.0.0",
        observation_source_identifier="warehouse://test",
        observation_fingerprint="sha256:test",
        differences=(
            ReconciliationDifference(
                difference_type=ReconciliationDifferenceType.MISMATCH,
                subject=ReconciliationSubject.PHYSICAL_TYPE,
                reason_code=RuntimeReasonCode.RUNTIME_PHYSICAL_TYPE_CHANGED,
                path="schema[orders].properties[id].physicalType",
                asset_identity="orders",
                property_identity="id",
                expected="BIGINT",
                observed="STRING",
            ),
        ),
        unverified_paths=(),
    )
    return RuntimeReconciliation(
        platform="warehouse",
        runtime_target="analytics",
        bindings=(binding,),
        result=result,
        status=RuntimeDriftStatus.DRIFT,
    )


def test_reconcile_parser_is_product_and_provider_scoped() -> None:
    args = cli._build_parser().parse_args(
        [
            "reconcile",
            "--contract",
            "contracts/sales.yaml",
            "--platform",
            "warehouse",
            "--runtime",
            "analytics",
            "--output",
            "json",
        ]
    )

    assert args.command == "reconcile"
    assert args.contract == "contracts/sales.yaml"
    assert args.platform == "warehouse"
    assert args.runtime == "analytics"
    assert args.output == "json"
    assert not hasattr(args, "workspace_url")
    assert not hasattr(args, "token")


def test_json_output_is_deterministic_and_product_scoped() -> None:
    payload = json.loads(reconcile_cmd._format_json(_analysis()))

    assert payload["platform"] == "warehouse"
    assert payload["runtimeTarget"] == "analytics"
    assert payload["status"] == "DRIFT"
    assert payload["bindings"][0]["governedAsset"] == "orders"
    difference = payload["reconciliation"]["differences"][0]
    assert difference["reason_code"] == "RUNTIME_PHYSICAL_TYPE_CHANGED"
    assert difference["path"] == "schema[orders].properties[id].physicalType"


@pytest.mark.parametrize(
    "outcome,expected_exit",
    [
        (ProcessOutcome.SUCCESS, 0),
        (ProcessOutcome.RUNTIME_DRIFT, 6),
        (ProcessOutcome.RUNTIME_INDETERMINATE, 7),
    ],
)
def test_main_preserves_runtime_assurance_exit_semantics(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    outcome: ProcessOutcome,
    expected_exit: int,
) -> None:
    monkeypatch.setattr(
        reconcile_cmd,
        "run_reconcile",
        lambda args: ReconcileCommandResult(output="result", outcome=outcome),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "semapact",
            "reconcile",
            "--contract",
            "contracts/sales.yaml",
            "--platform",
            "warehouse",
            "--runtime",
            "analytics",
        ],
    )

    assert cli.main() == expected_exit
    assert capsys.readouterr().out.strip() == "result"
