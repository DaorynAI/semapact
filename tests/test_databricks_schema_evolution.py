from __future__ import annotations

import pytest
from open_data_contract_standard.model import SchemaObject, SchemaProperty

from semapact.deployment.models import NativeOperationKind
from semapact.deployment.schema_transitions import (
    SchemaTransition,
    SchemaTransitionKind,
)
from semapact.exceptions import ValidationError
from semapact.observation.models import (
    ObservedAsset,
    ObservedAssetIdentity,
    ObservedProperty,
    ObservedPropertyIdentity,
)
from semapact.platforms.databricks.transition_compiler import (
    DatabricksTransitionCompiler,
)
from semapact.platforms.databricks.transition_planner import (
    DatabricksSchemaTransitionPlanner,
)
from semapact.schema import (
    SchemaSnapshot,
    SqlSchemaMapper,
    compare_schema_snapshots,
)


_MAPPER = SqlSchemaMapper(
    key="databricks",
    server_type="databricks",
    dialect="databricks",
)
_PLANNER = DatabricksSchemaTransitionPlanner()


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
) -> SchemaTransition:
    mapped = _MAPPER.map_desired_asset(
        desired,
        asset_identity="orders",
    )
    observed_assets = (
        ()
        if observed is None
        else (
            _MAPPER.map_observed_asset(
                observed,
                asset_identity="orders",
            ),
        )
    )
    comparison = compare_schema_snapshots(
        SchemaSnapshot(assets=(mapped,)),
        SchemaSnapshot(assets=observed_assets),
    )
    return _PLANNER.plan(
        governed_asset="orders",
        physical_name="orders",
        desired_columns=mapped.properties,
        comparison=comparison,
        observed_asset=observed,
    )


def _compile(transition: SchemaTransition):
    return DatabricksTransitionCompiler().compile(
        runtime_target="main.silver",
        transition=transition,
    )


def test_planner_and_compiler_create_missing_managed_delta_table() -> None:
    transition = _plan(
        _schema(_property("id", "BIGINT", required=True)),
        None,
    )

    assert transition.kind is SchemaTransitionKind.CREATE_ASSET
    assert transition.columns[0].identity == "id"
    assert transition.columns[0].physical_type == "BIGINT"
    assert transition.columns[0].nullable is False

    operation = _compile(transition)
    assert operation.kind is NativeOperationKind.CREATE
    assert operation.statement == (
        "CREATE TABLE `main`.`silver`.`orders` "
        "(`id` BIGINT NOT NULL) USING DELTA"
    )


def test_planner_and_compiler_add_only_missing_nullable_columns() -> None:
    transition = _plan(
        _schema(
            _property("id", "BIGINT", required=True),
            _property("note", "STRING"),
        ),
        _observed(("id", "bigint", False)),
    )

    assert transition.kind is SchemaTransitionKind.ADD_PROPERTIES
    assert [column.identity for column in transition.columns] == ["note"]

    operation = _compile(transition)
    assert operation.kind is NativeOperationKind.ALTER
    assert operation.statement == (
        "ALTER TABLE `main`.`silver`.`orders` "
        "ADD COLUMNS (`note` STRING)"
    )


def test_planner_no_ops_when_governed_shape_is_satisfied() -> None:
    transition = _plan(
        _schema(_property("id", "BIGINT", required=True)),
        _observed(
            ("id", "bigint", False),
            ("runtime_only", "string", True),
        ),
    )

    assert transition.kind is SchemaTransitionKind.NO_OP
    assert transition.columns == ()

    operation = _compile(transition)
    assert operation.kind is NativeOperationKind.NO_OP
    assert operation.statement is None


def test_desired_type_normalization_reuses_datacontract_mapping() -> None:
    transition = _plan(
        _schema(_property("id", "integer", required=True)),
        None,
    )
    assert transition.columns[0].physical_type == "INT"


def test_desired_target_schema_comes_from_datacontract_physical_projection() -> None:
    prop = SchemaProperty(
        name="logical_id",
        physicalName="physical_id",
        logicalType="integer",
        physicalType="integer",
        required=True,
    )

    transition = _plan(_schema(prop), None)

    assert transition.columns[0].identity == "physical_id"
    assert transition.columns[0].physical_type == "INT"
    assert transition.columns[0].nullable is False


def test_transition_compiler_executes_only_governed_physical_shape() -> None:
    prop = SchemaProperty(
        name="id",
        physicalName="id",
        logicalType="integer",
        physicalType="BIGINT",
        required=True,
        primaryKey=True,
        description="business identifier",
    )

    transition = _plan(_schema(prop), None)

    assert transition.columns[0].native_definition == "`id` BIGINT NOT NULL"
    operation = _compile(transition)
    assert operation.statement == (
        "CREATE TABLE `main`.`silver`.`orders` "
        "(`id` BIGINT NOT NULL) USING DELTA"
    )
    assert "PRIMARY KEY" not in operation.statement
    assert "COMMENT" not in operation.statement


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
def test_planner_fails_closed_on_unsafe_existing_mutation(
    desired: SchemaObject,
    observed: ObservedAsset,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _plan(desired, observed)


@pytest.mark.parametrize(
    ("desired_type", "observed_type"),
    [
        ("INT", "DECIMAL(18,2)"),
        ("DECIMAL(10,2)", "DECIMAL(18,2)"),
        ("DECIMAL(18,2)", "DECIMAL(18,4)"),
        ("DECIMAL(18,2)", "DECIMAL(10,2)"),
        ("BIGINT", "INT"),
    ],
)
def test_existing_numeric_type_changes_fail_closed(
    desired_type: str,
    observed_type: str,
) -> None:
    with pytest.raises(ValidationError, match="type mutation"):
        _plan(
            _schema(_property("amount", desired_type)),
            _observed(("amount", observed_type, True)),
        )


def test_planner_rejects_non_managed_asset_only_when_mutation_is_required() -> None:
    with pytest.raises(ValidationError, match="MANAGED"):
        _plan(
            _schema(
                _property("id", "BIGINT", required=True),
                _property("note", "STRING"),
            ),
            _observed(
                ("id", "bigint", False),
                asset_type="EXTERNAL",
            ),
        )


def test_planner_allows_no_op_assurance_for_non_managed_asset() -> None:
    transition = _plan(
        _schema(_property("id", "BIGINT", required=True)),
        _observed(
            ("id", "bigint", False),
            asset_type="EXTERNAL",
        ),
    )

    assert transition.kind is SchemaTransitionKind.NO_OP


def test_desired_schema_validation_rejects_unsafe_physical_type() -> None:
    with pytest.raises(
        ValidationError,
        match="physicalType|could not be parsed|exactly one CREATE TABLE",
    ):
        _MAPPER.map_desired_asset(
            _schema(_property("id", "STRING);DROP")),
            asset_identity="orders",
        )
