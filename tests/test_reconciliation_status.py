from __future__ import annotations

from semapact.reconciliation import (
    ReconciliationDifference,
    ReconciliationDifferenceType,
    ReconciliationResult,
    ReconciliationSubject,
    RuntimeDriftStatus,
    RuntimeReasonCode,
    classify_reconciliation_status,
)


def _result(
    *,
    differences: tuple[ReconciliationDifference, ...] = (),
    unverified_paths: tuple[str, ...] = (),
) -> ReconciliationResult:
    return ReconciliationResult(
        contract_id="orders-contract",
        contract_version="1.2.3",
        observation_source_identifier="https://adb.example",
        observation_fingerprint="fingerprint",
        differences=differences,
        unverified_paths=unverified_paths,
    )


def _difference() -> ReconciliationDifference:
    return ReconciliationDifference(
        difference_type=ReconciliationDifferenceType.MISMATCH,
        subject=ReconciliationSubject.PHYSICAL_TYPE,
        reason_code=RuntimeReasonCode.RUNTIME_PHYSICAL_TYPE_CHANGED,
        path="schema[orders].properties[id].physicalType",
        asset_identity="orders",
        property_identity="id",
        expected="BIGINT",
        observed="STRING",
    )


def test_complete_match_is_in_sync() -> None:
    assert classify_reconciliation_status(_result()) is RuntimeDriftStatus.IN_SYNC


def test_unverified_comparison_is_indeterminate() -> None:
    result = _result(
        unverified_paths=("schema[orders].properties[id].physicalType",)
    )

    assert (
        classify_reconciliation_status(result)
        is RuntimeDriftStatus.INDETERMINATE
    )


def test_proven_difference_is_drift_even_with_unverified_evidence() -> None:
    result = _result(
        differences=(_difference(),),
        unverified_paths=("schema[orders].properties[id].nullability",),
    )

    assert classify_reconciliation_status(result) is RuntimeDriftStatus.DRIFT
