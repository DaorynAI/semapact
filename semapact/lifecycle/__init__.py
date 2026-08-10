from semapact.lifecycle.helpers import (
    allows_breaking_changes,
    is_active_contract,
    normalize_status,
    schema_items,
)
from semapact.lifecycle.identity import (
    SchemaIdentity,
    PropertyIdentity,
    build_schema_index,
    build_property_index,
)
from semapact.lifecycle.merge_engine import (
    ContractMergeEngine,
    MergeConflict,
    MergeResult,
)
from semapact.lifecycle.policy import (
    BreakingChange,
    PolicyEvaluation,
    evaluate_merge_policy,
)
from semapact.lifecycle.relationships import (
    normalize_endpoint_value,
    normalize_relationship_endpoint,
)

__all__ = [
    "normalize_status",
    "is_active_contract",
    "allows_breaking_changes",
    "schema_items",
    "SchemaIdentity",
    "PropertyIdentity",
    "build_schema_index",
    "build_property_index",
    "normalize_relationship_endpoint",
    "normalize_endpoint_value",
    "ContractMergeEngine",
    "MergeConflict",
    "MergeResult",
    "BreakingChange",
    "PolicyEvaluation",
    "evaluate_merge_policy",
]
