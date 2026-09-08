from __future__ import annotations

import json
import sys

import pytest

from semapact.interfaces import cli
from semapact.interfaces.commands import reconcile_cmd
from semapact.interfaces.outcomes import (
    CliExitCode,
    ProcessOutcome,
    exit_code_from_reconciliation_status,
    outcome_from_reconciliation_status,
)
from semapact.reconciliation import (
    ReconciliationDifference,
    ReconciliationDifferenceType,
    ReconciliationResult,
    ReconciliationSubject,
    RuntimeDriftStatus,
    RuntimeReasonCode,
)
from semapact.services import ReconciliationAnalysis


def _analysis(status: RuntimeDriftStatus) -> ReconciliationAnalysis:
    differences: tuple[ReconciliationDifference, ...] = ()
    unverified_paths: tuple[str, ...] = ()
    if status is RuntimeDriftStatus.DRIFT:
        differences = (
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
        )
    elif status is RuntimeDriftStatus.INDETERMINATE:
        unverified_paths = ("schema[orders].properties[id].physicalType",)

    return ReconciliationAnalysis(
        runtime_target="main.sales.orders",
        result=ReconciliationResult(
            contract_id="orders-contract",
            contract_version="1.2.3",
            observation_source_identifier="https://adb.example",
            observation_fingerprint="obs-v1:sha256:test",
            differences=differences,
            unverified_paths=unverified_paths,
        ),
        status=status,
    )


@pytest.mark.parametrize(
    ("status", "outcome", "exit_code"),
    [
        (RuntimeDriftStatus.IN_SYNC, ProcessOutcome.SUCCESS, CliExitCode.SUCCESS),
        (
            RuntimeDriftStatus.DRIFT,
            ProcessOutcome.RUNTIME_DRIFT,
            CliExitCode.RUNTIME_DRIFT,
        ),
        (
            RuntimeDriftStatus.INDETERMINATE,
            ProcessOutcome.RUNTIME_INDETERMINATE,
            CliExitCode.RUNTIME_INDETERMINATE,
        ),
    ],
)
def test_runtime_assurance_status_has_distinct_process_semantics(
    status: RuntimeDriftStatus,
    outcome: ProcessOutcome,
    exit_code: CliExitCode,
) -> None:
    assert outcome_from_reconciliation_status(status) is outcome
    assert exit_code_from_reconciliation_status(status) is exit_code


def test_reconciliation_text_exposes_runtime_evidence() -> None:
    output = reconcile_cmd.format_reconciliation_text(_analysis(RuntimeDriftStatus.DRIFT))

    assert output == "\n".join(
        [
            "Contract: orders-contract",
            "Version: 1.2.3",
            "Runtime: main.sales.orders",
            "Status: DRIFT",
            "",
            "Differences:",
            "- RUNTIME_PHYSICAL_TYPE_CHANGED schema[orders].properties[id].physicalType expected='BIGINT' observed='STRING'",
            "",
            "Unverified:",
            "- none",
        ]
    )


def test_reconciliation_json_is_deterministic_machine_output() -> None:
    output = reconcile_cmd.format_reconciliation_json(
        _analysis(RuntimeDriftStatus.INDETERMINATE)
    )
    payload = json.loads(output)

    assert output == json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert payload["runtimeTarget"] == "main.sales.orders"
    assert payload["status"] == "INDETERMINATE"
    assert payload["reconciliation"]["unverified_paths"] == [
        "schema[orders].properties[id].physicalType"
    ]


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [
        (RuntimeDriftStatus.IN_SYNC, 0),
        (RuntimeDriftStatus.DRIFT, 6),
        (RuntimeDriftStatus.INDETERMINATE, 7),
    ],
)
def test_reconcile_cli_returns_ci_significant_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: RuntimeDriftStatus,
    expected_exit: int,
) -> None:
    monkeypatch.setattr(reconcile_cmd, "run_reconcile", lambda args: _analysis(status))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "semapact",
            "reconcile",
            "--contract",
            "contracts/orders.yaml",
            "--source",
            "main.sales.orders",
            "--output",
            "json",
        ],
    )

    assert cli.main() == expected_exit
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == status.value
