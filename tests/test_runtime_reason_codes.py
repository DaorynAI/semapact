from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.observation import (
    ObservedAsset,
    ObservedAssetIdentity,
    ObservedPlatformState,
    ObservedProperty,
    ObservedPropertyIdentity,
    with_observed_state_fingerprint,
)
from semapact.reconciliation import (
    ReconciliationDifferenceType,
    ReconciliationSubject,
    RuntimeReasonCode,
    reconcile_governed_contract,
    serialize_reconciliation_result,
)
from semapact.reconciliation.engine import _runtime_reason_code

CAPTURED_AT = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)


def _observed_asset(
    name: str,
    *properties: tuple[str, str | None, bool | None],
) -> ObservedAsset:
    identity = ObservedAssetIdentity(
        platform="databricks",
        namespace=("main", "silver"),
        asset=name,
    )
    return ObservedAsset(
        identity=identity,
        properties=tuple(
            ObservedProperty(
                identity=ObservedPropertyIdentity(asset=identity, property=property_name),
                physical_type=physical_type,
                nullable=nullable,
            )
            for property_name, physical_type, nullable in properties
        ),
    )


def _observation(*assets: ObservedAsset) -> ObservedPlatformState:
    state = ObservedPlatformState(
        platform="databricks",
        source_identifier="https://adb.example",
        assets=tuple(assets),
        captured_at=CAPTURED_AT,
        fingerprint=None,
    )
    return with_observed_state_fingerprint(state)


def test_supported_runtime_differences_have_stable_reason_codes() -> None:
    contract = OpenDataContractStandard.model_construct(
        id="orders-contract",
        version="1.2.3",
        schema_=[
            SchemaObject(name="customers", properties=[]),
            SchemaObject(
                name="orders",
                properties=[
                    SchemaProperty(
                        name="id",
                        type="integer",
                        physicalType="BIGINT",
                        required=True,
                    ),
                    SchemaProperty(
                        name="amount",
                        type="number",
                        physicalType="DOUBLE",
                    ),
                ],
            ),
        ],
    )
    observation = _observation(
        _observed_asset(
            "orders",
            ("id", "STRING", True),
            ("note", "STRING", True),
        ),
        _observed_asset("payments"),
    )

    result = reconcile_governed_contract(contract, observation)

    assert {difference.reason_code for difference in result.differences} == {
        RuntimeReasonCode.RUNTIME_SCHEMA_ADDED,
        RuntimeReasonCode.RUNTIME_SCHEMA_REMOVED,
        RuntimeReasonCode.RUNTIME_PROPERTY_ADDED,
        RuntimeReasonCode.RUNTIME_PROPERTY_REMOVED,
        RuntimeReasonCode.RUNTIME_PHYSICAL_TYPE_CHANGED,
        RuntimeReasonCode.RUNTIME_REQUIRED_CHANGED,
    }

    by_code = {difference.reason_code: difference for difference in result.differences}
    assert by_code[RuntimeReasonCode.RUNTIME_SCHEMA_REMOVED].path == "schema[customers]"
    assert by_code[RuntimeReasonCode.RUNTIME_SCHEMA_ADDED].path == "schema[payments]"
    assert (
        by_code[RuntimeReasonCode.RUNTIME_PROPERTY_REMOVED].path
        == "schema[orders].properties[amount]"
    )
    assert (
        by_code[RuntimeReasonCode.RUNTIME_PROPERTY_ADDED].path
        == "schema[orders].properties[note]"
    )
    assert (
        by_code[RuntimeReasonCode.RUNTIME_PHYSICAL_TYPE_CHANGED].expected == "BIGINT"
    )
    assert (
        by_code[RuntimeReasonCode.RUNTIME_PHYSICAL_TYPE_CHANGED].observed == "STRING"
    )
    assert by_code[RuntimeReasonCode.RUNTIME_REQUIRED_CHANGED].expected is False
    assert by_code[RuntimeReasonCode.RUNTIME_REQUIRED_CHANGED].observed is True


def test_runtime_reason_code_is_serialized_with_existing_raw_evidence() -> None:
    contract = OpenDataContractStandard.model_construct(
        id="orders-contract",
        version="1.2.3",
        schema_=[SchemaObject(name="orders", properties=[])],
    )
    result = reconcile_governed_contract(contract, _observation())

    payload = json.loads(serialize_reconciliation_result(result))

    assert payload["differences"] == [
        {
            "asset_identity": "orders",
            "difference_type": "missing",
            "expected": None,
            "observed": None,
            "path": "schema[orders]",
            "property_identity": None,
            "reason_code": "RUNTIME_SCHEMA_REMOVED",
            "subject": "asset",
        }
    ]


def test_unregistered_raw_difference_combination_fails_explicitly() -> None:
    with pytest.raises(
        ValueError,
        match="Unsupported runtime difference combination: mismatch/asset",
    ):
        _runtime_reason_code(
            difference_type=ReconciliationDifferenceType.MISMATCH,
            subject=ReconciliationSubject.ASSET,
        )
