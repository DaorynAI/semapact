from __future__ import annotations

import pytest
from open_data_contract_standard.model import SchemaObject, SchemaProperty

from semapact.deployment.models import NativeOperation, NativeOperationKind
from semapact.exceptions import ValidationError
from semapact.observation.models import (
    ObservedAsset,
    ObservedAssetIdentity,
    ObservedProperty,
    ObservedPropertyIdentity,
)
from semapact.platforms.databricks.schema_evolution import (
    plan_databricks_schema_evolution,
    validate_databricks_desired_schema,
)


def _property(
    name: str,
    physical_type: str,
    *,
    required: bool = False,
) -> SchemaProperty:
    return SchemaProperty(
        name=name,
        physicalName=name,
        logicalType="string",
        physicalType=physical_type,
        required=required,
    )


def _schema(*properties: SchemaProperty) -> SchemaObject:
    return SchemaObject(
        name="orders",
        physicalName="orders",
        physicalType="table",
        properties=list(properties),
    )


def _observed(
    *columns: tuple[str, str, bool],
    asset_type: str = "MANAGED",
) -> ObservedAsset:
    identity = ObservedAssetIdentity(
        platform="databricks",
        namespace=("main", "silver"),
        asset="orders",
    )
    return ObservedAsset(
        identity=identity,
        asset_type=asset_type,
        properties=tuple(
            ObservedProperty(
                identity=ObservedPropertyIdentity(
                    asset=identity,
                    property=name,
                ),
                physical_type=physical_type,
                nullable=nullable,
            )
            for name, physical_type, nullable in columns
        ),
    )


def _plan(
    desired: SchemaObject,
    observed: ObservedAsset | None,
) -> NativeOperation:
    return plan_databricks_schema_evolution(
        catalog="main",
        schema_name="silver",
        governed_asset="orders",
        table_name="orders",
        desired=desired,
        observed=observed,
    )


def test_pure_planner_creates_missing_managed_delta_table() -> None:
    operation = _plan(
        _schema(_property("id", "BIGINT", required=True)),
        None,
    )

    assert operation.kind is NativeOperationKind.CREATE
    assert operation.statement == (
        "CREATE TABLE `main`.`silver`.`orders` "
        "(`id` BIGINT NOT NULL) USING DELTA"
    )


def test_pure_planner_adds_only_missing_nullable_columns() -> None:
    operation = _plan(
        _schema(
            _property("id", "BIGINT", required=True),
            _property("note", "STRING"),
        ),
        _observed(("id", "bigint", False)),
    )

    assert operation.kind is NativeOperationKind.ALTER
    assert operation.statement == (
        "ALTER TABLE `main`.`silver`.`orders` "
        "ADD COLUMNS (`note` STRING)"
    )


def test_pure_planner_no_ops_when_governed_shape_is_satisfied() -> None:
    operation = _plan(
        _schema(_property("id", "BIGINT", required=True)),
        _observed(
            ("id", "bigint", False),
            ("runtime_only", "string", True),
        ),
    )

    assert operation.kind is NativeOperationKind.NO_OP
    assert operation.statement is None


@pytest.mark.parametrize(
    ("desired", "observed", "message"),
    [
        (
            _schema(_property("id", "STRING", required=True)),
            _observed(("id", "bigint", False)),
            "type mutation",
        ),
        (
            _schema(_property("id", "BIGINT", required=True)),
            _observed(("id", "bigint", True)),
            "nullability mutation",
        ),
        (
            _schema(
                _property("id", "BIGINT", required=True),
                _property("required_new", "STRING", required=True),
            ),
            _observed(("id", "bigint", False)),
            "safe default",
        ),
    ],
)
def test_pure_planner_fails_closed_on_unsafe_existing_mutation(
    desired: SchemaObject,
    observed: ObservedAsset,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _plan(desired, observed)


def test_pure_planner_rejects_non_managed_asset() -> None:
    with pytest.raises(ValidationError, match="MANAGED"):
        _plan(
            _schema(_property("id", "BIGINT", required=True)),
            _observed(("id", "bigint", False), asset_type="EXTERNAL"),
        )


def test_desired_schema_validation_rejects_unsafe_physical_type() -> None:
    with pytest.raises(ValidationError, match="physicalType"):
        validate_databricks_desired_schema(
            table_name="orders",
            desired=_schema(_property("id", "STRING);DROP")),
        )


def test_pure_planner_rejects_observation_for_different_asset() -> None:
    observed = _observed(("id", "bigint", False)).model_copy(
        update={
            "identity": ObservedAssetIdentity(
                platform="databricks",
                namespace=("main", "silver"),
                asset="customers",
            )
        }
    )
    with pytest.raises(ValidationError, match="Observed asset"):
        _plan(_schema(_property("id", "BIGINT", required=True)), observed)
