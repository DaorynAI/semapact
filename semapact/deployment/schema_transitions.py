"""Provider-neutral additive schema-transition planning.

This module compares normalized desired and observed column state. It owns no
provider naming, SQL rendering, credentials, runtime observation, governance,
authorization, or execution semantics.
"""

from __future__ import annotations

from enum import Enum
from typing import Sequence

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from semapact.exceptions import ValidationError


class SchemaTransitionModel(BaseModel):
    """Shared immutable base for internal schema-transition values."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class SchemaTransitionKind(str, Enum):
    """Semantic runtime transitions supported by the initial additive planner."""

    CREATE_ASSET = "CREATE_ASSET"
    ADD_PROPERTIES = "ADD_PROPERTIES"
    NO_OP = "NO_OP"


class SchemaColumnState(SchemaTransitionModel):
    """One normalized physical column state used for transition comparison."""

    name: str
    physical_type: str
    nullable: bool

    @field_validator("name", "physical_type")
    @classmethod
    def _require_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("schema column state fields must not be empty")
        return cleaned


class SchemaTransition(SchemaTransitionModel):
    """One semantic desired-to-runtime transition before provider compilation."""

    kind: SchemaTransitionKind
    governed_asset: str
    physical_name: str
    columns: tuple[SchemaColumnState, ...] = ()

    @field_validator("governed_asset", "physical_name")
    @classmethod
    def _require_identity_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("schema transition identity fields must not be empty")
        return cleaned

    @model_validator(mode="after")
    def _validate_shape(self) -> "SchemaTransition":
        if self.kind is SchemaTransitionKind.NO_OP:
            if self.columns:
                raise ValueError("NO_OP schema transition must not carry columns")
            return self
        if not self.columns:
            raise ValueError(f"{self.kind.value} schema transition requires columns")
        if self.kind is SchemaTransitionKind.ADD_PROPERTIES and any(
            not column.nullable for column in self.columns
        ):
            raise ValueError(
                "ADD_PROPERTIES transition may contain only nullable columns"
            )
        return self


def plan_additive_schema_transition(
    *,
    governed_asset: str,
    physical_name: str,
    desired_columns: Sequence[SchemaColumnState],
    observed_columns: Sequence[SchemaColumnState] | None,
) -> SchemaTransition:
    """Plan the initial fail-closed additive schema-evolution subset.

    observed_columns=None means the asset is absent. Runtime-only extra columns
    are intentionally ignored; this planner never infers DROP.
    """
    desired = tuple(desired_columns)
    if not desired:
        raise ValidationError("Schema transition requires at least one desired column")

    _index_columns(desired, role="desired")

    if observed_columns is None:
        return SchemaTransition(
            kind=SchemaTransitionKind.CREATE_ASSET,
            governed_asset=governed_asset,
            physical_name=physical_name,
            columns=desired,
        )

    observed = tuple(observed_columns)
    observed_by_name = _index_columns(observed, role="observed")

    additions: list[SchemaColumnState] = []
    for column in desired:
        current = observed_by_name.get(column.name.casefold())
        if current is None:
            if not column.nullable:
                raise ValidationError(
                    f"Cannot add required column '{column.name}' without a safe default"
                )
            additions.append(column)
            continue

        if current.physical_type.casefold() != column.physical_type.casefold():
            raise ValidationError(
                f"Unsupported existing column type mutation for '{column.name}': "
                f"{current.physical_type} -> {column.physical_type}"
            )
        if current.nullable is not column.nullable:
            raise ValidationError(
                f"Unsupported existing column nullability mutation for '{column.name}'"
            )

    if additions:
        return SchemaTransition(
            kind=SchemaTransitionKind.ADD_PROPERTIES,
            governed_asset=governed_asset,
            physical_name=physical_name,
            columns=tuple(additions),
        )

    return SchemaTransition(
        kind=SchemaTransitionKind.NO_OP,
        governed_asset=governed_asset,
        physical_name=physical_name,
    )


def _index_columns(
    columns: Sequence[SchemaColumnState],
    *,
    role: str,
) -> dict[str, SchemaColumnState]:
    index: dict[str, SchemaColumnState] = {}
    for column in columns:
        key = column.name.casefold()
        if key in index:
            raise ValidationError(
                f"Duplicate normalized {role} column identity: '{column.name}'"
            )
        index[key] = column
    return index
