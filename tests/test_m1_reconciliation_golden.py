from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

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
)
from semapact.observation.fingerprint import fingerprint_observed_state
from semapact.reconciliation import (
    RuntimeReasonCode,
    classify_reconciliation_status,
    reconcile_governed_contract,
    serialize_reconciliation_result,
)

CAPTURED_AT = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
GOLDEN_PATH = Path(__file__).parent / "fixtures" / "m1_reconciliation_golden.json"
ScenarioFactory = Callable[[], tuple[OpenDataContractStandard, ObservedPlatformState]]


def _contract(*schemas: SchemaObject) -> OpenDataContractStandard:
    return OpenDataContractStandard.model_construct(
        id="orders-contract",
        version="1.2.3",
        schema_=list(schemas),
    )


def _asset(
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
        asset_type="MANAGED",
        properties=tuple(
            ObservedProperty(
                identity=ObservedPropertyIdentity(
                    asset=identity,
                    property=property_name,
                ),
                physical_type=physical_type,
                nullable=nullable,
            )
            for property_name, physical_type, nullable in properties
        ),
    )


def _observation(*assets: ObservedAsset) -> ObservedPlatformState:
    return ObservedPlatformState(
        platform="databricks",
        source_identifier="https://adb.example",
        assets=tuple(assets),
        captured_at=CAPTURED_AT,
        fingerprint=None,
    )


def _in_sync_scenario() -> tuple[OpenDataContractStandard, ObservedPlatformState]:
    contract = _contract(
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
                    required=False,
                ),
            ],
        )
    )
    observation = _observation(
        _asset(
            "orders",
            ("id", "bigint", False),
            ("amount", "DOUBLE", True),
        )
    )
    return contract, observation


def _indeterminate_scenario() -> tuple[OpenDataContractStandard, ObservedPlatformState]:
    contract = _contract(
        SchemaObject(
            name="orders",
            properties=[
                SchemaProperty(
                    name="id",
                    type="integer",
                    physicalType="BIGINT",
                    required=True,
                )
            ],
        )
    )
    observation = _observation(_asset("orders", ("id", None, None)))
    return contract, observation


def _composite_drift_scenario(
    *,
    reverse_order: bool = False,
) -> tuple[OpenDataContractStandard, ObservedPlatformState]:
    governed_properties = [
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
        SchemaProperty(
            name="created_at",
            type="timestamp",
            physicalType="TIMESTAMP",
            required=True,
        ),
    ]
    observed_properties = [
        ("id", "STRING", True),
        ("note", "STRING", True),
        ("created_at", None, None),
    ]
    if reverse_order:
        governed_properties = list(reversed(governed_properties))
        observed_properties = list(reversed(observed_properties))

    customers = SchemaObject(name="customers", properties=[])
    orders = SchemaObject(name="orders", properties=governed_properties)
    observed_orders = _asset("orders", *observed_properties)
    payments = _asset("payments")

    if reverse_order:
        return _contract(orders, customers), _observation(payments, observed_orders)
    return _contract(customers, orders), _observation(observed_orders, payments)


def _golden() -> dict[str, dict[str, object]]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("scenario_name", "scenario"),
    [
        ("in_sync", _in_sync_scenario),
        ("indeterminate", _indeterminate_scenario),
        ("composite_drift", _composite_drift_scenario),
    ],
)
def test_m1_reconciliation_matches_golden_contract(
    scenario_name: str,
    scenario: ScenarioFactory,
) -> None:
    contract, observation = scenario()
    result = reconcile_governed_contract(contract, observation)
    expected = _golden()[scenario_name]

    serialized = serialize_reconciliation_result(result)
    expected_serialized = json.dumps(
        expected["reconciliation"],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    assert serialized == expected_serialized
    assert classify_reconciliation_status(result).value == expected["status"]


def test_composite_golden_covers_every_supported_runtime_reason_code() -> None:
    contract, observation = _composite_drift_scenario()
    result = reconcile_governed_contract(contract, observation)

    assert {difference.reason_code for difference in result.differences} == set(
        RuntimeReasonCode
    )


def test_equivalent_upstream_order_is_byte_equivalent() -> None:
    left_contract, left_observation = _composite_drift_scenario()
    right_contract, right_observation = _composite_drift_scenario(reverse_order=True)

    left = reconcile_governed_contract(left_contract, left_observation)
    right = reconcile_governed_contract(right_contract, right_observation)

    assert serialize_reconciliation_result(left) == serialize_reconciliation_result(right)
    assert fingerprint_observed_state(left_observation) == fingerprint_observed_state(
        right_observation
    )
