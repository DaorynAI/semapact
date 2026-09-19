from __future__ import annotations

import pytest
from open_data_contract_standard.model import SchemaObject, SchemaProperty

from semapact.deployment.models import NativeOperationKind
from semapact.deployment.schema_transitions import (
    SchemaTransition,
    SchemaTransitionKind,
    plan_schema_transition,
)
from semapact.exceptions import ValidationError
from semapact.observation.models import (
    ObservedAsset,
    ObservedAssetIdentity,
    ObservedProperty,
    ObservedPropertyIdentity,
)
from semapact.platforms.databricks.platform import DatabricksDeploymentPlatform
from semapact.platforms.databricks.transition_compiler import (
    DatabricksTransitionCompiler,
)





class _UnusedRuntimeProvider:
    def resolve_bindings(self, *, runtime_target, assets):
        raise AssertionError("runtime provider should not be used in schema unit tests")

    def observe(self, *, bindings):
        raise AssertionError("runtime provider should not be used in schema unit tests")


_PLATFORM = DatabricksDeploymentPlatform(
    runtime_provider=_UnusedRuntimeProvider(),
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
) -> SchemaTransition:
    mapped = _PLATFORM.schema_mapper.map_desired_asset(
        desired,
        asset_identity="orders",
    )
    _PLATFORM.validate_desired_asset(
        target=_deployment_target(),
        physical_name="orders",
        desired=desired,
        mapped=mapped,
    )
    if observed is not None:
        _PLATFORM.validate_observed_asset(
            target=_deployment_target(),
            physical_name="orders",
            observed=observed,
        )
    return plan_schema_transition(
        mapper=_PLATFORM.schema_mapper,
        governed_asset="orders",
        physical_name="orders",
        desired=desired,
        observed=observed,
    )


def _deployment_target():
    from semapact.deployment.models import DeploymentTarget

    return DeploymentTarget(
        platform="databricks",
        runtime_target="main.silver",
        source_reference="https://workspace.example",
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


def test_planner_rejects_non_managed_asset() -> None:
    with pytest.raises(ValidationError, match="MANAGED"):
        _plan(
            _schema(_property("id", "BIGINT", required=True)),
            _observed(("id", "bigint", False), asset_type="EXTERNAL"),
        )


def test_desired_schema_validation_rejects_unsafe_physical_type() -> None:
    with pytest.raises(ValidationError, match="physicalType|could not be parsed"):
        _PLATFORM.schema_mapper.map_desired_asset(
            _schema(_property("id", "STRING);DROP")),
            asset_identity="orders",
        )


def test_planner_rejects_observation_for_different_asset() -> None:
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
