from __future__ import annotations

import pytest

from semapact.deployment.schema_transitions import (
    SchemaTransitionKind,
    plan_additive_schema_transition,
)
from semapact.exceptions import ValidationError
from semapact.schema import (
    SchemaAssetState,
    SchemaPropertyState,
    SchemaSnapshot,
    compare_schema_snapshots,
)


def _column(name: str, physical_type: str, *, nullable: bool) -> SchemaPropertyState:
    return SchemaPropertyState(
        identity=name,
        physical_type=physical_type,
        nullable=nullable,
    )


def _compare(
    desired: tuple[SchemaPropertyState, ...],
    observed: tuple[SchemaPropertyState, ...] | None,
):
    expected = SchemaSnapshot(
        assets=(SchemaAssetState(identity="orders", properties=desired),)
    )
    actual = SchemaSnapshot(
        assets=()
        if observed is None
        else (SchemaAssetState(identity="orders", properties=observed),)
    )
    return compare_schema_snapshots(expected, actual)


def test_transition_planner_consumes_shared_missing_property_difference() -> None:
    desired = (
        _column("id", "BIGINT", nullable=False),
        _column("note", "STRING", nullable=True),
    )

    transition = plan_additive_schema_transition(
        governed_asset="orders",
        physical_name="orders",
        desired_columns=desired,
        comparison=_compare(
            desired,
            (_column("id", "BIGINT", nullable=False),),
        ),
    )

    assert transition.kind is SchemaTransitionKind.ADD_PROPERTIES
    assert transition.columns == (desired[1],)


def test_transition_planner_never_interprets_runtime_only_property_as_drop() -> None:
    desired = (_column("id", "BIGINT", nullable=False),)

    transition = plan_additive_schema_transition(
        governed_asset="orders",
        physical_name="orders",
        desired_columns=desired,
        comparison=_compare(
            desired,
            (
                _column("id", "BIGINT", nullable=False),
                _column("runtime_only", "STRING", nullable=True),
            ),
        ),
    )

    assert transition.kind is SchemaTransitionKind.NO_OP


def test_transition_planner_interprets_missing_asset_as_create() -> None:
    desired = (_column("id", "BIGINT", nullable=False),)

    transition = plan_additive_schema_transition(
        governed_asset="orders",
        physical_name="orders",
        desired_columns=desired,
        comparison=_compare(desired, None),
    )

    assert transition.kind is SchemaTransitionKind.CREATE_ASSET
    assert transition.columns == desired


def test_transition_planner_fails_closed_on_required_addition() -> None:
    desired = (
        _column("id", "BIGINT", nullable=False),
        _column("required_new", "STRING", nullable=False),
    )
    with pytest.raises(ValidationError, match="safe default"):
        plan_additive_schema_transition(
            governed_asset="orders",
            physical_name="orders",
            desired_columns=desired,
            comparison=_compare(
                desired,
                (_column("id", "BIGINT", nullable=False),),
            ),
        )


def test_transition_planner_fails_closed_on_type_mismatch_fact() -> None:
    desired = (_column("id", "BIGINT", nullable=False),)
    with pytest.raises(ValidationError, match="type mutation"):
        plan_additive_schema_transition(
            governed_asset="orders",
            physical_name="orders",
            desired_columns=desired,
            comparison=_compare(
                desired,
                (_column("id", "STRING", nullable=False),),
            ),
        )
