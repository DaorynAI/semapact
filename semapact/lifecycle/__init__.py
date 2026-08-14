from semapact.lifecycle.helpers import (
    schema_items,
)
from semapact.lifecycle.status import (
    LIFECYCLE_STATUS_PROPERTY,
    LifecycleStatus,
    is_active_contract,
    is_explicitly_deprecated,
    is_retired_contract,
    lifecycle_from_custom_properties,
    normalize_status,
    participates_in_breaking_checks,
    resolve_contract_lifecycle,
    resolve_declared_entity_lifecycle,
    resolve_property_lifecycle,
    resolve_schema_lifecycle,
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
    "LIFECYCLE_STATUS_PROPERTY",
    "LifecycleStatus",
    "normalize_status",
    "lifecycle_from_custom_properties",
    "resolve_contract_lifecycle",
    "resolve_declared_entity_lifecycle",
    "resolve_schema_lifecycle",
    "resolve_property_lifecycle",
    "is_active_contract",
    "is_retired_contract",
    "participates_in_breaking_checks",
    "is_explicitly_deprecated",
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

