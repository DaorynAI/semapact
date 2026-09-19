"""Provider-neutral schema state comparison primitives."""

from semapact.schema.comparison import (
    SchemaAssetState,
    SchemaComparisonResult,
    SchemaDifference,
    SchemaDifferenceType,
    SchemaPropertyState,
    SchemaSnapshot,
    SchemaSubject,
    compare_schema_snapshots,
)

__all__ = [
    "SchemaAssetState",
    "SchemaComparisonResult",
    "SchemaDifference",
    "SchemaDifferenceType",
    "SchemaPropertyState",
    "SchemaSnapshot",
    "SchemaSubject",
    "compare_schema_snapshots",
    "PassThroughSchemaMapper",
    "SchemaMapper",
    "build_physical_property_bindings",
    "map_desired_schema_asset",
    "map_observed_schema_asset",
    "property_identity",
]

from semapact.schema.mapping import (
    PassThroughSchemaMapper,
    SchemaMapper,
    build_physical_property_bindings,
    map_desired_schema_asset,
    map_observed_schema_asset,
    property_identity,
)
