"""Databricks deployment schema planning.

This module applies Databricks runtime/capability constraints around the shared
schema mapper, comparator, and provider-neutral transition planner.
"""

from __future__ import annotations

from open_data_contract_standard.model import SchemaObject

from semapact.deployment.schema_transitions import (
    SchemaTransition,
    plan_additive_schema_transition,
)
from semapact.exceptions import ValidationError
from semapact.observation.models import ObservedAsset
from semapact.platforms.databricks.identifiers import (
    validate_databricks_identifier,
)
from semapact.platforms.databricks.schema_mapper import DATABRICKS_SCHEMA_MAPPER
from semapact.platforms.databricks.target import parse_databricks_runtime_target
from semapact.schema import SchemaAssetState, SchemaSnapshot, compare_schema_snapshots


def validate_databricks_desired_schema(
    *,
    table_name: str,
    desired: SchemaObject,
) -> None:
    """Validate compiled desired state against the supported write-side subset."""
    asset = DATABRICKS_SCHEMA_MAPPER.map_desired_asset(
        desired,
        asset_identity=table_name,
    )
    _validate_databricks_asset_state(asset)


def plan_databricks_schema_transition(
    *,
    runtime_target: str,
    governed_asset: str,
    table_name: str,
    desired: SchemaObject,
    observed: ObservedAsset | None,
) -> SchemaTransition:
    """Apply Databricks capability constraints around shared schema planning."""
    catalog, schema_name = parse_databricks_runtime_target(runtime_target)
    validate_databricks_identifier(catalog, "catalog")
    validate_databricks_identifier(schema_name, "schema")

    desired_asset = DATABRICKS_SCHEMA_MAPPER.map_desired_asset(
        desired,
        asset_identity=table_name,
    )
    _validate_databricks_asset_state(desired_asset)

    if observed is not None:
        _validate_databricks_observed_asset(
            observed=observed,
            catalog=catalog,
            schema_name=schema_name,
            table_name=table_name,
        )
        observed_assets = (
            DATABRICKS_SCHEMA_MAPPER.map_observed_asset(
                observed,
                asset_identity=table_name,
            ),
        )
    else:
        observed_assets = ()

    comparison = compare_schema_snapshots(
        SchemaSnapshot(assets=(desired_asset,)),
        SchemaSnapshot(assets=observed_assets),
    )
    return plan_additive_schema_transition(
        governed_asset=governed_asset,
        physical_name=table_name,
        desired_columns=desired_asset.properties,
        comparison=comparison,
    )


def _validate_databricks_asset_state(asset: SchemaAssetState) -> None:
    validate_databricks_identifier(asset.identity, "asset")
    if not asset.properties:
        raise ValidationError(
            "Databricks deployment requires at least one schema property"
        )
    for prop in asset.properties:
        validate_databricks_identifier(prop.identity, "column")


def _validate_databricks_observed_asset(
    *,
    observed: ObservedAsset,
    catalog: str,
    schema_name: str,
    table_name: str,
) -> None:
    if observed.identity.platform.casefold() != "databricks":
        raise ValidationError(
            "Databricks deployment planning requires Databricks runtime evidence"
        )

    expected_namespace = (catalog.casefold(), schema_name.casefold())
    actual_namespace = tuple(part.casefold() for part in observed.identity.namespace)
    if actual_namespace != expected_namespace:
        raise ValidationError(
            "Observed asset is outside the requested Databricks namespace"
        )

    if observed.identity.asset.casefold() != table_name.casefold():
        raise ValidationError(
            "Observed asset does not match the requested Databricks table"
        )

    if (observed.asset_type or "").strip().casefold() != "managed":
        raise ValidationError(
            "Existing Databricks asset must be a MANAGED table for deployment mutation"
        )
