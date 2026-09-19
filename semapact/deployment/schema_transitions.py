"""Interpret raw schema differences as additive convergence intent.

Comparison belongs to semapact.schema. This module consumes the shared comparison
result and maps facts into the initial deployment transition vocabulary. It does
not compare desired and observed schemas itself.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Sequence

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from semapact.exceptions import ValidationError
from semapact.observation.models import ObservedAsset
from semapact.schema import (
    SchemaComparisonResult,
    SchemaDifferenceType,
    SchemaPropertyState,
    SchemaSubject,
)


class SchemaTransitionModel(BaseModel):
    """Shared immutable base for internal schema-transition values."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class SchemaTransitionKind(str, Enum):
    """Semantic runtime transitions supported by the initial additive planner."""

    CREATE_ASSET = "CREATE_ASSET"
    ADD_PROPERTIES = "ADD_PROPERTIES"
    NO_OP = "NO_OP"


class SchemaTransition(SchemaTransitionModel):
    """One semantic desired-to-runtime transition before provider compilation."""

    kind: SchemaTransitionKind
    governed_asset: str
    physical_name: str
    columns: tuple[SchemaPropertyState, ...] = ()

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
        return self






class SchemaTransitionPlanner(ABC):
    """Interpret factual schema differences as provider-supported convergence intent."""

    key: str

    @abstractmethod
    def plan(
        self,
        *,
        governed_asset: str,
        physical_name: str,
        desired_columns: Sequence[SchemaPropertyState],
        comparison: SchemaComparisonResult,
        observed_asset: ObservedAsset | None = None,
    ) -> SchemaTransition:
        raise NotImplementedError


class AdditiveSchemaTransitionPlanner(SchemaTransitionPlanner):
    """Shared fail-closed planner for the initial additive schema subset."""

    key = "additive"

    def plan(
        self,
        *,
        governed_asset: str,
        physical_name: str,
        desired_columns: Sequence[SchemaPropertyState],
        comparison: SchemaComparisonResult,
        observed_asset: ObservedAsset | None = None,
    ) -> SchemaTransition:
        del observed_asset
        return plan_additive_schema_transition(
            governed_asset=governed_asset,
            physical_name=physical_name,
            desired_columns=desired_columns,
            comparison=comparison,
        )

def plan_additive_schema_transition(
    *,
    governed_asset: str,
    physical_name: str,
    desired_columns: Sequence[SchemaPropertyState],
    comparison: SchemaComparisonResult,
) -> SchemaTransition:
    """Interpret shared schema differences for the initial additive subset."""
    desired = tuple(desired_columns)
    if not desired:
        raise ValidationError("Schema transition requires at least one desired column")

    desired_by_name = _index_desired_columns(desired)
    asset_key = physical_name.casefold()

    if comparison.unverified_paths:
        raise ValidationError(
            "Runtime schema evidence is incomplete for deployment transition planning"
        )

    relevant = tuple(
        difference
        for difference in comparison.differences
        if difference.asset_identity.casefold() == asset_key
    )

    missing_asset = any(
        difference.difference_type is SchemaDifferenceType.MISSING
        and difference.subject is SchemaSubject.ASSET
        for difference in relevant
    )
    if missing_asset:
        return SchemaTransition(
            kind=SchemaTransitionKind.CREATE_ASSET,
            governed_asset=governed_asset,
            physical_name=physical_name,
            columns=desired,
        )

    additions: list[SchemaPropertyState] = []
    for difference in relevant:
        if (
            difference.difference_type is SchemaDifferenceType.UNEXPECTED
            and difference.subject is SchemaSubject.PROPERTY
        ):
            # Runtime-only columns never imply DROP.
            continue

        if (
            difference.difference_type is SchemaDifferenceType.MISSING
            and difference.subject is SchemaSubject.PROPERTY
        ):
            property_identity = difference.property_identity
            if property_identity is None:
                raise ValidationError("Missing property difference has no property identity")
            column = desired_by_name.get(property_identity.casefold())
            if column is None:
                raise ValidationError(
                    f"Schema difference references unknown desired property '{property_identity}'"
                )
            if column.nullable is not True:
                raise ValidationError(
                    f"Cannot add required column '{column.identity}' without a safe default"
                )
            additions.append(column)
            continue

        if (
            difference.difference_type is SchemaDifferenceType.MISMATCH
            and difference.subject is SchemaSubject.PHYSICAL_TYPE
        ):
            raise ValidationError(
                f"Unsupported existing column type mutation for "
                f"'{difference.property_identity}': "
                f"{difference.observed} -> {difference.expected}"
            )

        if (
            difference.difference_type is SchemaDifferenceType.MISMATCH
            and difference.subject is SchemaSubject.NULLABILITY
        ):
            raise ValidationError(
                f"Unsupported existing column nullability mutation for "
                f"'{difference.property_identity}'"
            )

        if difference.subject is SchemaSubject.ASSET:
            raise ValidationError(
                "Unsupported runtime asset difference for additive deployment planning"
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


def _index_desired_columns(
    columns: Sequence[SchemaPropertyState],
) -> dict[str, SchemaPropertyState]:
    index: dict[str, SchemaPropertyState] = {}
    for column in columns:
        key = column.identity.casefold()
        if key in index:
            raise ValidationError(
                f"Duplicate normalized desired column identity: '{column.identity}'"
            )
        index[key] = column
    return index
