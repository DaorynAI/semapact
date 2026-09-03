from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.exceptions import ValidationError
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
    reconcile_governed_contract,
    serialize_reconciliation_result,
)

CAPTURED_AT = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)


def _contract(*schemas: SchemaObject) -> OpenDataContractStandard:
    return OpenDataContractStandard.model_construct(
        id="orders-contract",
        version="1.2.3",
        schema_=list(schemas),
    )


def _property(
    *,
    asset: ObservedAssetIdentity,
    name: str,
    physical_type: str | None,
    nullable: bool | None,
) -> ObservedProperty:
    return ObservedProperty(
        identity=ObservedPropertyIdentity(asset=asset, property=name),
        physical_type=physical_type,
        nullable=nullable,
    )


def _asset(
    name: str,
    *properties: tuple[str, str | None, bool | None],
    namespace: tuple[str, ...] = ("main", "silver"),
) -> ObservedAsset:
    identity = ObservedAssetIdentity(
        platform="databricks",
        namespace=namespace,
        asset=name,
    )
    return ObservedAsset(
        identity=identity,
        properties=tuple(
            _property(
                asset=identity,
                name=prop_name,
                physical_type=physical_type,
                nullable=nullable,
            )
            for prop_name, physical_type, nullable in properties
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


def test_exact_comparable_state_has_no_differences() -> None:
    contract = _contract(
        SchemaObject(
            name=" Orders ",
            properties=[
                SchemaProperty(
                    name="Order_ID",
                    type="integer",
                    physicalType="BIGINT",
                    required=True,
                ),
                SchemaProperty(
                    name="amount",
                    type="number",
                    physicalType="DECIMAL(18,2)",
                    required=False,
                ),
            ],
        )
    )
    observation = _observation(
        _asset(
            "orders",
            ("order_id", "bigint", False),
            ("amount", "decimal(18,2)", True),
            namespace=("other_catalog", "other_schema"),
        )
    )

    result = reconcile_governed_contract(contract, observation)

    assert result.differences == ()
    assert result.has_differences is False
    assert result.contract_id == "orders-contract"
    assert result.contract_version == "1.2.3"
    assert result.observation_fingerprint == observation.fingerprint


def test_missing_and_unexpected_assets_and_properties_are_reported() -> None:
    contract = _contract(
        SchemaObject(
            name="orders",
            properties=[
                SchemaProperty(name="id", type="integer", physicalType="BIGINT"),
                SchemaProperty(name="amount", type="number", physicalType="DOUBLE"),
            ],
        ),
        SchemaObject(name="customers", properties=[]),
    )
    observation = _observation(
        _asset(
            "orders",
            ("id", "bigint", None),
            ("note", "string", True),
        ),
        _asset("payments"),
    )

    result = reconcile_governed_contract(contract, observation)

    assert [
        (item.difference_type, item.subject, item.path)
        for item in result.differences
    ] == [
        (
            ReconciliationDifferenceType.MISSING,
            ReconciliationSubject.ASSET,
            "schema[customers]",
        ),
        (
            ReconciliationDifferenceType.MISSING,
            ReconciliationSubject.PROPERTY,
            "schema[orders].properties[amount]",
        ),
        (
            ReconciliationDifferenceType.UNEXPECTED,
            ReconciliationSubject.PROPERTY,
            "schema[orders].properties[note]",
        ),
        (
            ReconciliationDifferenceType.UNEXPECTED,
            ReconciliationSubject.ASSET,
            "schema[payments]",
        ),
    ]


def test_physical_type_and_nullability_mismatches_are_reported() -> None:
    contract = _contract(
        SchemaObject(
            name="orders",
            properties=[
                SchemaProperty(
                    name="customer_id",
                    type="integer",
                    physicalType="BIGINT",
                    required=True,
                )
            ],
        )
    )
    observation = _observation(
        _asset("orders", ("customer_id", "STRING", True))
    )

    result = reconcile_governed_contract(contract, observation)

    assert len(result.differences) == 2
    physical, nullable = result.differences
    assert physical.subject is ReconciliationSubject.PHYSICAL_TYPE
    assert physical.expected == "BIGINT"
    assert physical.observed == "STRING"
    assert nullable.subject is ReconciliationSubject.NULLABILITY
    assert nullable.expected is False
    assert nullable.observed is True


def test_unknown_comparable_values_are_not_guessed() -> None:
    contract = _contract(
        SchemaObject(
            name="orders",
            properties=[SchemaProperty(name="id", type="integer")],
        )
    )
    observation = _observation(_asset("orders", ("id", None, None)))

    result = reconcile_governed_contract(contract, observation)

    assert result.differences == ()


def test_duplicate_canonical_observed_asset_identity_fails_closed() -> None:
    contract = _contract(SchemaObject(name="orders", properties=[]))
    observation = _observation(
        _asset("orders", namespace=("main", "one")),
        _asset(" ORDERS ", namespace=("main", "two")),
    )

    with pytest.raises(
        ValidationError,
        match="Duplicate canonical observed asset identity found: 'orders'",
    ):
        reconcile_governed_contract(contract, observation)


def test_duplicate_canonical_observed_property_identity_fails_closed() -> None:
    contract = _contract(
        SchemaObject(
            name="orders",
            properties=[SchemaProperty(name="id", type="integer")],
        )
    )
    observation = _observation(
        _asset(
            "orders",
            ("id", "bigint", False),
            (" ID ", "bigint", False),
        )
    )

    with pytest.raises(
        ValidationError,
        match="Duplicate canonical observed property identity found: 'id'",
    ):
        reconcile_governed_contract(contract, observation)


def test_difference_order_and_serialization_are_deterministic() -> None:
    orders = SchemaObject(
        name="orders",
        properties=[
            SchemaProperty(name="z_col", type="string", physicalType="STRING"),
            SchemaProperty(name="a_col", type="integer", physicalType="BIGINT"),
        ],
    )
    users = SchemaObject(name="users", properties=[])
    contract_left = _contract(users, orders)
    contract_right = _contract(orders, users)

    orders_observed = _asset(
        "orders",
        ("extra", "string", True),
        ("a_col", "string", None),
    )
    payments_observed = _asset("payments")
    observation_left = _observation(payments_observed, orders_observed)
    observation_right = _observation(orders_observed, payments_observed)

    left = reconcile_governed_contract(contract_left, observation_left)
    right = reconcile_governed_contract(contract_right, observation_right)

    assert left.differences == right.differences
    assert serialize_reconciliation_result(left) == serialize_reconciliation_result(right)


def test_reconciliation_does_not_mutate_inputs() -> None:
    contract = _contract(
        SchemaObject(
            name="orders",
            properties=[
                SchemaProperty(name="id", type="integer", physicalType="BIGINT")
            ],
        )
    )
    observation = _observation(_asset("orders", ("id", "string", False)))
    contract_before = deepcopy(contract.model_dump())
    observation_before = observation.model_dump()

    reconcile_governed_contract(contract, observation)

    assert contract.model_dump() == contract_before
    assert observation.model_dump() == observation_before
