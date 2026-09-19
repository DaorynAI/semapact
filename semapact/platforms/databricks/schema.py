"""Databricks schema provider configuration and provider-specific constraints."""

from __future__ import annotations

from open_data_contract_standard.model import SchemaObject

from semapact.exceptions import ValidationError
from semapact.observation.models import ObservedAsset
from semapact.platforms.databricks.identifiers import validate_databricks_identifier
from semapact.schema import SchemaAssetState, SqlSchemaMapper


DATABRICKS_SCHEMA_MAPPER = SqlSchemaMapper(
    key="databricks",
    server_type="databricks",
    dialect="databricks",
)


def validate_databricks_desired_schema(
    *,
    table_name: str,
    desired: SchemaObject,
) -> SchemaAssetState:
    """Compile desired state through datacontract-cli and validate executable identities."""
    asset = DATABRICKS_SCHEMA_MAPPER.map_desired_asset(
        desired,
        asset_identity=table_name,
    )
    validate_databricks_schema_asset(asset)
    return asset


def validate_databricks_schema_asset(asset: SchemaAssetState) -> None:
    """Validate the Databricks-specific executable identifier subset."""
    validate_databricks_identifier(asset.identity, "asset")
    for prop in asset.properties:
        validate_databricks_identifier(prop.identity, "column")


def validate_databricks_observed_asset(
    *,
    observed: ObservedAsset,
    catalog: str,
    schema_name: str,
    table_name: str,
) -> None:
    """Validate runtime evidence required by the Databricks write-side."""
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
