"""Databricks implementation of the generic deployment platform contract."""

from __future__ import annotations

from open_data_contract_standard.model import SchemaObject

from semapact.deployment.models import DeploymentTarget
from semapact.deployment.schema_transitions import AdditiveSchemaTransitionPlanner
from semapact.deployment.providers import DeploymentPlatform
from semapact.exceptions import ValidationError
from semapact.observation.models import ObservedAsset
from semapact.observation.providers import RuntimeProvider
from semapact.platforms.databricks.target import parse_databricks_runtime_target
from semapact.platforms.databricks.transition_compiler import (
    DatabricksTransitionCompiler,
)
from semapact.schema import (
    SchemaAssetState,
    SqlSchemaMapper,
    validate_simple_sql_identifier,
)


class DatabricksDeploymentPlatform(DeploymentPlatform):
    """Databricks-specific target and runtime constraints only."""

    key = "databricks"

    def __init__(self, *, runtime_provider: RuntimeProvider) -> None:
        self.runtime_provider = runtime_provider
        self.schema_mapper = SqlSchemaMapper(
            key=self.key,
            server_type="databricks",
            dialect="databricks",
        )
        self.transition_planner = AdditiveSchemaTransitionPlanner()
        self.transition_compiler = DatabricksTransitionCompiler()

    def validate_target(self, target: DeploymentTarget) -> None:
        catalog, schema_name = parse_databricks_runtime_target(
            target.runtime_target
        )
        validate_simple_sql_identifier(catalog, "catalog")
        validate_simple_sql_identifier(schema_name, "schema")

    def validate_desired_asset(
        self,
        *,
        target: DeploymentTarget,
        physical_name: str,
        desired: SchemaObject,
        mapped: SchemaAssetState,
    ) -> None:
        del target, desired
        validate_simple_sql_identifier(physical_name, "asset")
        if mapped.identity.casefold() != physical_name.casefold():
            raise ValidationError(
                "Mapped desired asset identity does not match physical target"
            )
        for prop in mapped.properties:
            validate_simple_sql_identifier(prop.identity, "column")

    def validate_observed_asset(
        self,
        *,
        target: DeploymentTarget,
        physical_name: str,
        observed: ObservedAsset,
    ) -> None:
        catalog, schema_name = parse_databricks_runtime_target(
            target.runtime_target
        )

        if observed.identity.platform.casefold() != self.key:
            raise ValidationError(
                "Databricks deployment requires Databricks runtime evidence"
            )

        expected_namespace = (catalog.casefold(), schema_name.casefold())
        actual_namespace = tuple(
            part.casefold()
            for part in observed.identity.namespace
        )
        if actual_namespace != expected_namespace:
            raise ValidationError(
                "Observed asset is outside the requested Databricks namespace"
            )

        if observed.identity.asset.casefold() != physical_name.casefold():
            raise ValidationError(
                "Observed asset does not match the requested Databricks table"
            )

        if (observed.asset_type or "").strip().casefold() != "managed":
            raise ValidationError(
                "Existing Databricks asset must be a MANAGED table for deployment mutation"
            )
