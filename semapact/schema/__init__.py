"""Provider-neutral schema state, mapping and comparison primitives."""

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
from semapact.schema.identifiers import validate_simple_sql_identifier
from semapact.schema.mapping import (
    PassThroughSchemaMapper,
    SchemaMapper,
    SqlSchemaMapper,
    build_physical_property_bindings,
    map_odcs_schema_asset,
    map_observed_schema_asset,
    normalize_sql_type,
    parse_sql_target_asset,
    property_identity,
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
    "SqlSchemaMapper",
    "build_physical_property_bindings",
    "map_odcs_schema_asset",
    "map_observed_schema_asset",
    "property_identity",
    "parse_sql_target_asset",
    "normalize_sql_type",
    "validate_simple_sql_identifier",
]
