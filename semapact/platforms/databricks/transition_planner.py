"""Databricks schema-transition capability policy."""

from __future__ import annotations

from collections.abc import Sequence

from semapact.deployment.schema_transitions import (
    AdditiveSchemaTransitionPlanner,
    SchemaTransition,
    SchemaTransitionKind,
    SchemaTransitionPlanner,
)
from semapact.exceptions import ValidationError
from semapact.observation.models import ObservedAsset
from semapact.schema import SchemaComparisonResult, SchemaPropertyState


class DatabricksSchemaTransitionPlanner(SchemaTransitionPlanner):
    """Apply Databricks mutation capability rules around shared additive planning."""

    key = "databricks"

    def __init__(self) -> None:
        self._additive = AdditiveSchemaTransitionPlanner()

    def plan(
        self,
        *,
        governed_asset: str,
        physical_name: str,
        desired_columns: Sequence[SchemaPropertyState],
        comparison: SchemaComparisonResult,
        observed_asset: ObservedAsset | None = None,
    ) -> SchemaTransition:
        transition = self._additive.plan(
            governed_asset=governed_asset,
            physical_name=physical_name,
            desired_columns=desired_columns,
            comparison=comparison,
            observed_asset=observed_asset,
        )

        if (
            observed_asset is not None
            and transition.kind is not SchemaTransitionKind.NO_OP
            and (observed_asset.asset_type or "").strip().casefold() != "managed"
        ):
            raise ValidationError(
                "Existing Databricks asset must be a MANAGED table for deployment mutation"
            )

        return transition
