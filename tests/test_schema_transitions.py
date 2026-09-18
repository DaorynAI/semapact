from __future__ import annotations

import pytest

from semapact.deployment.schema_transitions import (
    SchemaColumnState,
    SchemaTransitionKind,
    plan_additive_schema_transition,
)
from semapact.exceptions import ValidationError


def _column(name: str, physical_type: str, *, nullable: bool) -> SchemaColumnState:
    return SchemaColumnState(
        name=name,
        physical_type=physical_type,
        nullable=nullable,
    )


def test_additive_transition_planner_is_provider_neutral() -> None:
    desired = (
        _column("id", "BIGINT", nullable=False),
        _column("note", "STRING", nullable=True),
    )
    observed = (_column("id", "BIGINT", nullable=False),)

    transition = plan_additive_schema_transition(
        governed_asset="orders",
        physical_name="orders",
        desired_columns=desired,
        observed_columns=observed,
    )

    assert transition.kind is SchemaTransitionKind.ADD_PROPERTIES
    assert transition.columns == (desired[1],)


def test_additive_transition_planner_never_infers_drop() -> None:
    desired = (_column("id", "BIGINT", nullable=False),)
    observed = (
        _column("id", "BIGINT", nullable=False),
        _column("runtime_only", "STRING", nullable=True),
    )

    transition = plan_additive_schema_transition(
        governed_asset="orders",
        physical_name="orders",
        desired_columns=desired,
        observed_columns=observed,
    )

    assert transition.kind is SchemaTransitionKind.NO_OP


def test_additive_transition_planner_fails_closed_on_required_addition() -> None:
    with pytest.raises(ValidationError, match="safe default"):
        plan_additive_schema_transition(
            governed_asset="orders",
            physical_name="orders",
            desired_columns=(
                _column("id", "BIGINT", nullable=False),
                _column("required_new", "STRING", nullable=False),
            ),
            observed_columns=(_column("id", "BIGINT", nullable=False),),
        )
