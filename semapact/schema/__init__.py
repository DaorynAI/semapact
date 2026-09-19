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
]
