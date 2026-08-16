"""Canonical ODCS-aware semantic change representation for governed contract evolution."""

from __future__ import annotations

import json
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, JsonValue

from open_data_contract_standard.model import (
    CustomProperty,
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)
from semapact.governance_codes import GovernanceReasonCode
from semapact.lifecycle.identity import (
    build_property_index,
    build_schema_index,
    normalize_identity_name,
)
from semapact.lifecycle.relationships import normalize_endpoint_value
from semapact.lifecycle.status import (
    is_explicitly_deprecated,
    resolve_declared_entity_lifecycle,
)


# ==============================================================================
# ODCS Field Coverage Contract
# ==============================================================================

# 1. Root contract fields
ODCS_ROOT_SPECIAL_FIELDS: frozenset[str] = frozenset({
    "id",
    "version",
    "status",
    "schema_",
    "tags",
    "customProperties",
})

ODCS_ROOT_METADATA_FIELDS: frozenset[str] = frozenset({
    "name",
    "description",
    "domain",
    "dataProduct",
    "tenant",
    "team",
    "price",
    "slaDefaultElement",
    "slaProperties",
    "support",
    "roles",
    "apiVersion",
    "kind",
})

ODCS_ROOT_STRUCTURAL_FIELDS: frozenset[str] = frozenset({
    "servers",
    "contractCreatedTs",
    "authoritativeDefinitions",
})

ODCS_ROOT_HANDLED_FIELDS: frozenset[str] = (
    ODCS_ROOT_SPECIAL_FIELDS
    | ODCS_ROOT_METADATA_FIELDS
    | ODCS_ROOT_STRUCTURAL_FIELDS
)
ODCS_ROOT_IGNORED_FIELDS: frozenset[str] = frozenset()

# 2. Schema fields
ODCS_SCHEMA_SPECIAL_FIELDS: frozenset[str] = frozenset({
    "name",
    "properties",
    "relationships",
    "quality",
    "tags",
    "customProperties",
})

ODCS_SCHEMA_METADATA_FIELDS: frozenset[str] = frozenset({
    "description",
    "businessName",
})

ODCS_SCHEMA_STRUCTURAL_FIELDS: frozenset[str] = frozenset({
    "logicalType",
    "physicalType",
    "physicalName",
    "id",
    "dataGranularityDescription",
    "authoritativeDefinitions",
})

ODCS_SCHEMA_HANDLED_FIELDS: frozenset[str] = (
    ODCS_SCHEMA_SPECIAL_FIELDS
    | ODCS_SCHEMA_METADATA_FIELDS
    | ODCS_SCHEMA_STRUCTURAL_FIELDS
)
ODCS_SCHEMA_IGNORED_FIELDS: frozenset[str] = frozenset()

# 3. Property fields
ODCS_PROPERTY_SPECIAL_FIELDS: frozenset[str] = frozenset({
    "name",
    "properties",
    "items",
    "relationships",
    "quality",
    "tags",
    "customProperties",
})

ODCS_PROPERTY_METADATA_FIELDS: frozenset[str] = frozenset({
    "description",
    "businessName",
    "classification",
    "examples",
    "transformDescription",
    "authoritativeDefinitions",
})

ODCS_PROPERTY_STRUCTURAL_FIELDS: frozenset[str] = frozenset({
    "logicalType",
    "logicalTypeOptions",
    "physicalType",
    "physicalName",
    "required",
    "primaryKey",
    "primaryKeyPosition",
    "unique",
    "partitioned",
    "partitionKeyPosition",
    "id",
    "encryptedName",
    "transformSourceObjects",
    "transformLogic",
    "criticalDataElement",
})

ODCS_PROPERTY_HANDLED_FIELDS: frozenset[str] = (
    ODCS_PROPERTY_SPECIAL_FIELDS
    | ODCS_PROPERTY_METADATA_FIELDS
    | ODCS_PROPERTY_STRUCTURAL_FIELDS
)
ODCS_PROPERTY_IGNORED_FIELDS: frozenset[str] = frozenset()


class GovernanceChangeType(str, Enum):
    """Semantic type of contract change."""

    ADD = "ADD"
    REMOVE = "REMOVE"
    MODIFY = "MODIFY"
    DEPRECATE = "DEPRECATE"


class GovernanceEntityType(str, Enum):
    """Governed entity level for the change."""

    CONTRACT = "CONTRACT"
    SCHEMA = "SCHEMA"
    PROPERTY = "PROPERTY"
    RELATIONSHIP = "RELATIONSHIP"
    QUALITY = "QUALITY"


class GovernanceChangeDomain(str, Enum):
    """Governance categorization domain for release and policy evaluation."""

    IDENTITY = "IDENTITY"
    VERSION = "VERSION"
    LIFECYCLE = "LIFECYCLE"
    STRUCTURE = "STRUCTURE"
    RELATIONSHIP = "RELATIONSHIP"
    QUALITY = "QUALITY"
    METADATA = "METADATA"


class GovernanceChangeEvidenceSource(str, Enum):
    """Source of change evidence."""

    MERGE_CONFLICT = "MERGE_CONFLICT"


class GovernanceChangeEvidence(BaseModel):
    """Typed evidence correlated with a canonical governance change."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: GovernanceChangeEvidenceSource
    code: str


class GovernanceChange(BaseModel):
    """Canonical, deterministic semantic change between governed base and candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    change_type: GovernanceChangeType
    entity_type: GovernanceEntityType

    identity: tuple[str, ...]
    path: str
    field: str | None = None

    before: JsonValue | None = None
    after: JsonValue | None = None

    domain: GovernanceChangeDomain

    breaking: bool = False
    reason_codes: tuple[GovernanceReasonCode, ...] = ()

    evidence: tuple[GovernanceChangeEvidence, ...] = ()


def governance_change_sort_key(change: GovernanceChange) -> tuple[Any, ...]:
    """Canonical sort key for deterministic ordering of governance changes."""
    return (
        change.identity,
        change.path,
        change.entity_type.value,
        change.change_type.value,
        change.field or "",
    )


def describe_governance_change(change: GovernanceChange) -> str:
    """Generate a clear, human-readable description for explainability."""
    target = ".".join(change.identity)
    if change.change_type == GovernanceChangeType.ADD:
        return f"Added {change.entity_type.value.lower()} '{target}'"
    if change.change_type == GovernanceChangeType.REMOVE:
        return f"Removed {change.entity_type.value.lower()} '{target}'"
    if change.change_type == GovernanceChangeType.DEPRECATE:
        return f"Deprecated {change.entity_type.value.lower()} '{target}'"
    if change.change_type == GovernanceChangeType.MODIFY:
        field_desc = f" {change.field}" if change.field else ""
        return (
            f"Modified {change.entity_type.value.lower()} '{target}'{field_desc} "
            f"from {change.before!r} to {change.after!r}"
        )
    return f"{change.change_type.value} on {target}"


# ==============================================================================
# Canonical Change Analyzer
# ==============================================================================


def analyze_governance_changes(
    base_contract: OpenDataContractStandard,
    candidate_contract: OpenDataContractStandard,
) -> tuple[GovernanceChange, ...]:
    """Analyze and return all canonical semantic differences between base and candidate."""
    if not isinstance(base_contract, OpenDataContractStandard):
        raise TypeError(f"base_contract must be OpenDataContractStandard, got {type(base_contract).__name__}")
    if not isinstance(candidate_contract, OpenDataContractStandard):
        raise TypeError(f"candidate_contract must be OpenDataContractStandard, got {type(candidate_contract).__name__}")

    changes: list[GovernanceChange] = []

    # 1. Contract root comparisons
    changes.extend(_analyze_contract_root(base_contract, candidate_contract))

    # 2. Schema and property comparisons
    changes.extend(_analyze_schemas_and_properties(base_contract, candidate_contract))

    # 3. Relationship comparisons
    changes.extend(_analyze_relationships(base_contract, candidate_contract))

    # 4. Quality rule comparisons
    changes.extend(_analyze_quality_rules(base_contract, candidate_contract))

    # Deterministic sorting
    sorted_changes = sorted(changes, key=governance_change_sort_key)
    return tuple(sorted_changes)


def _to_json_compatible(value: Any) -> JsonValue:
    """Normalize any Pydantic model, list, or primitive to a valid JsonValue."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump(by_alias=True, exclude_none=True, mode="json")
    if isinstance(value, (list, tuple)):
        return [_to_json_compatible(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _to_json_compatible(v) for k, v in value.items()}
    # Fallback to json dump/load roundtrip
    return json.loads(json.dumps(value, default=str))


def _analyze_contract_root(
    base: OpenDataContractStandard,
    candidate: OpenDataContractStandard,
) -> list[GovernanceChange]:
    changes: list[GovernanceChange] = []
    contract_id = str(base.id or candidate.id or "")
    identity = (contract_id,)

    # ID change
    base_id = str(base.id or "").strip()
    cand_id = str(candidate.id or "").strip()
    if base_id != cand_id:
        changes.append(
            GovernanceChange(
                change_type=GovernanceChangeType.MODIFY,
                entity_type=GovernanceEntityType.CONTRACT,
                identity=identity,
                path="id",
                field="id",
                before=base_id or None,
                after=cand_id or None,
                domain=GovernanceChangeDomain.IDENTITY,
            )
        )

    # Version change
    base_ver = str(base.version or "").strip()
    cand_ver = str(candidate.version or "").strip()
    if base_ver != cand_ver:
        changes.append(
            GovernanceChange(
                change_type=GovernanceChangeType.MODIFY,
                entity_type=GovernanceEntityType.CONTRACT,
                identity=identity,
                path="version",
                field="version",
                before=base_ver or None,
                after=cand_ver or None,
                domain=GovernanceChangeDomain.VERSION,
            )
        )

    # Status / Lifecycle change
    base_status = str(base.status or "").strip().lower()
    cand_status = str(candidate.status or "").strip().lower()
    if base_status != cand_status:
        if base_status != "retired" and cand_status == "retired":
            changes.append(
                GovernanceChange(
                    change_type=GovernanceChangeType.DEPRECATE,
                    entity_type=GovernanceEntityType.CONTRACT,
                    identity=identity,
                    path="status",
                    field="status",
                    before=base_status or None,
                    after="retired",
                    domain=GovernanceChangeDomain.LIFECYCLE,
                )
            )
        else:
            changes.append(
                GovernanceChange(
                    change_type=GovernanceChangeType.MODIFY,
                    entity_type=GovernanceEntityType.CONTRACT,
                    identity=identity,
                    path="status",
                    field="status",
                    before=base_status or None,
                    after=cand_status or None,
                    domain=GovernanceChangeDomain.LIFECYCLE,
                )
            )

    # Structural root fields
    for field_name in sorted(ODCS_ROOT_STRUCTURAL_FIELDS):
        base_val = getattr(base, field_name, None)
        cand_val = getattr(candidate, field_name, None)
        if _to_json_compatible(base_val) != _to_json_compatible(cand_val):
            changes.append(
                GovernanceChange(
                    change_type=GovernanceChangeType.MODIFY,
                    entity_type=GovernanceEntityType.CONTRACT,
                    identity=identity,
                    path=field_name,
                    field=field_name,
                    before=_to_json_compatible(base_val),
                    after=_to_json_compatible(cand_val),
                    domain=GovernanceChangeDomain.STRUCTURE,
                )
            )

    # Descriptive metadata fields and dynamic model fields
    metadata_fields = sorted(
        ODCS_ROOT_METADATA_FIELDS
        | (set(OpenDataContractStandard.model_fields) - ODCS_ROOT_HANDLED_FIELDS)
    )
    for field_name in metadata_fields:
        base_val = getattr(base, field_name, None)
        cand_val = getattr(candidate, field_name, None)
        if _to_json_compatible(base_val) != _to_json_compatible(cand_val):
            changes.append(
                GovernanceChange(
                    change_type=GovernanceChangeType.MODIFY,
                    entity_type=GovernanceEntityType.CONTRACT,
                    identity=identity,
                    path=field_name,
                    field=field_name,
                    before=_to_json_compatible(base_val),
                    after=_to_json_compatible(cand_val),
                    domain=GovernanceChangeDomain.METADATA,
                )
            )

    # Tags
    base_tags = sorted(str(t) for t in (base.tags or []))
    cand_tags = sorted(str(t) for t in (candidate.tags or []))
    if base_tags != cand_tags:
        changes.append(
            GovernanceChange(
                change_type=GovernanceChangeType.MODIFY,
                entity_type=GovernanceEntityType.CONTRACT,
                identity=identity,
                path="tags",
                field="tags",
                before=base_tags or None,
                after=cand_tags or None,
                domain=GovernanceChangeDomain.METADATA,
            )
        )

    # customProperties on contract
    changes.extend(
        _compare_custom_properties(
            identity=identity,
            path="customProperties",
            base_props=base.customProperties,
            cand_props=candidate.customProperties,
            is_deprecated_transition=False,
            entity_type=GovernanceEntityType.CONTRACT,
        )
    )

    return changes


def _analyze_schemas_and_properties(
    base_contract: OpenDataContractStandard,
    candidate_contract: OpenDataContractStandard,
) -> list[GovernanceChange]:
    changes: list[GovernanceChange] = []
    base_schemas = build_schema_index(base_contract)
    cand_schemas = build_schema_index(candidate_contract)

    # Added schemas
    for schema_id in sorted(set(cand_schemas) - set(base_schemas)):
        cand_schema = cand_schemas[schema_id]
        changes.append(
            GovernanceChange(
                change_type=GovernanceChangeType.ADD,
                entity_type=GovernanceEntityType.SCHEMA,
                identity=(schema_id,),
                path=f"schema[{schema_id}]",
                before=None,
                after=_to_json_compatible(cand_schema),
                domain=GovernanceChangeDomain.STRUCTURE,
            )
        )

    # Removed schemas
    for schema_id in sorted(set(base_schemas) - set(cand_schemas)):
        base_schema = base_schemas[schema_id]
        changes.append(
            GovernanceChange(
                change_type=GovernanceChangeType.REMOVE,
                entity_type=GovernanceEntityType.SCHEMA,
                identity=(schema_id,),
                path=f"schema[{schema_id}]",
                before=_to_json_compatible(base_schema),
                after=None,
                domain=GovernanceChangeDomain.STRUCTURE,
            )
        )

    # Matching schemas
    for schema_id in sorted(set(base_schemas) & set(cand_schemas)):
        base_schema = base_schemas[schema_id]
        cand_schema = cand_schemas[schema_id]
        schema_path = f"schema[{schema_id}]"
        schema_ident = (schema_id,)

        base_is_dep = is_explicitly_deprecated(base_schema)
        cand_is_dep = is_explicitly_deprecated(cand_schema)
        schema_deprecated_transition = not base_is_dep and cand_is_dep

        if schema_deprecated_transition:
            base_status = resolve_declared_entity_lifecycle(base_schema)
            base_status_str = base_status.value if base_status is not None else None
            changes.append(
                GovernanceChange(
                    change_type=GovernanceChangeType.DEPRECATE,
                    entity_type=GovernanceEntityType.SCHEMA,
                    identity=schema_ident,
                    path=schema_path,
                    field="lifecycleStatus",
                    before=base_status_str,
                    after="deprecated",
                    domain=GovernanceChangeDomain.LIFECYCLE,
                )
            )

        # Structural attributes
        for field_name in sorted(ODCS_SCHEMA_STRUCTURAL_FIELDS):
            b_val = getattr(base_schema, field_name, None)
            c_val = getattr(cand_schema, field_name, None)
            if b_val != c_val:
                changes.append(
                    GovernanceChange(
                        change_type=GovernanceChangeType.MODIFY,
                        entity_type=GovernanceEntityType.SCHEMA,
                        identity=schema_ident,
                        path=f"{schema_path}.{field_name}",
                        field=field_name,
                        before=_to_json_compatible(b_val),
                        after=_to_json_compatible(c_val),
                        domain=GovernanceChangeDomain.STRUCTURE,
                    )
                )

        # Metadata attributes and dynamic model fields
        schema_metadata_fields = sorted(
            ODCS_SCHEMA_METADATA_FIELDS
            | (set(SchemaObject.model_fields) - ODCS_SCHEMA_HANDLED_FIELDS)
        )
        for field_name in schema_metadata_fields:
            b_val = getattr(base_schema, field_name, None)
            c_val = getattr(cand_schema, field_name, None)
            if _to_json_compatible(b_val) != _to_json_compatible(c_val):
                changes.append(
                    GovernanceChange(
                        change_type=GovernanceChangeType.MODIFY,
                        entity_type=GovernanceEntityType.SCHEMA,
                        identity=schema_ident,
                        path=f"{schema_path}.{field_name}",
                        field=field_name,
                        before=_to_json_compatible(b_val),
                        after=_to_json_compatible(c_val),
                        domain=GovernanceChangeDomain.METADATA,
                    )
                )

        # Tags (suppressing companion "deprecated" tag if schema underwent deprecation)
        base_tags = [t for t in (base_schema.tags or [])]
        cand_tags = [t for t in (cand_schema.tags or [])]
        if schema_deprecated_transition:
            cand_tags = [t for t in cand_tags if t != "deprecated"]
        if sorted(base_tags) != sorted(cand_tags):
            changes.append(
                GovernanceChange(
                    change_type=GovernanceChangeType.MODIFY,
                    entity_type=GovernanceEntityType.SCHEMA,
                    identity=schema_ident,
                    path=f"{schema_path}.tags",
                    field="tags",
                    before=sorted(base_tags) or None,
                    after=sorted(cand_tags) or None,
                    domain=GovernanceChangeDomain.METADATA,
                )
            )

        # Custom properties
        changes.extend(
            _compare_custom_properties(
                identity=schema_ident,
                path=f"{schema_path}.customProperties",
                base_props=base_schema.customProperties,
                cand_props=cand_schema.customProperties,
                is_deprecated_transition=schema_deprecated_transition,
                entity_type=GovernanceEntityType.SCHEMA,
            )
        )

        # Compare properties recursively
        changes.extend(
            _compare_properties(
                schema_id=schema_id,
                ancestry=schema_ident,
                base_props=base_schema.properties or [],
                cand_props=cand_schema.properties or [],
                parent_path=schema_path,
            )
        )

    return changes


def _compare_properties(
    *,
    schema_id: str,
    ancestry: tuple[str, ...],
    base_props: list[SchemaProperty],
    cand_props: list[SchemaProperty],
    parent_path: str,
) -> list[GovernanceChange]:
    changes: list[GovernanceChange] = []
    scope_key = ancestry[-1]
    base_index = build_property_index(scope_key, base_props)
    cand_index = build_property_index(scope_key, cand_props)

    # Added properties
    for prop_key in sorted(set(cand_index) - set(base_index)):
        cand_prop = cand_index[prop_key]
        prop_name = prop_key[1]
        prop_ident = (*ancestry, prop_name)
        prop_path = f"{parent_path}.properties[{prop_name}]"
        changes.append(
            GovernanceChange(
                change_type=GovernanceChangeType.ADD,
                entity_type=GovernanceEntityType.PROPERTY,
                identity=prop_ident,
                path=prop_path,
                before=None,
                after=_to_json_compatible(cand_prop),
                domain=GovernanceChangeDomain.STRUCTURE,
            )
        )

    # Removed properties
    for prop_key in sorted(set(base_index) - set(cand_index)):
        base_prop = base_index[prop_key]
        prop_name = prop_key[1]
        prop_ident = (*ancestry, prop_name)
        prop_path = f"{parent_path}.properties[{prop_name}]"
        changes.append(
            GovernanceChange(
                change_type=GovernanceChangeType.REMOVE,
                entity_type=GovernanceEntityType.PROPERTY,
                identity=prop_ident,
                path=prop_path,
                before=_to_json_compatible(base_prop),
                after=None,
                domain=GovernanceChangeDomain.STRUCTURE,
            )
        )

    # Matching properties
    for prop_key in sorted(set(base_index) & set(cand_index)):
        base_prop = base_index[prop_key]
        cand_prop = cand_index[prop_key]
        prop_name = prop_key[1]
        prop_ident = (*ancestry, prop_name)
        prop_path = f"{parent_path}.properties[{prop_name}]"
        changes.extend(
            _compare_single_property_direct(
                schema_id=schema_id,
                prop_ident=prop_ident,
                prop_path=prop_path,
                base_prop=base_prop,
                cand_prop=cand_prop,
            )
        )

    return changes


def _compare_single_property_direct(
    *,
    schema_id: str,
    prop_ident: tuple[str, ...],
    prop_path: str,
    base_prop: SchemaProperty,
    cand_prop: SchemaProperty,
) -> list[GovernanceChange]:
    changes: list[GovernanceChange] = []
    base_is_dep = is_explicitly_deprecated(base_prop)
    cand_is_dep = is_explicitly_deprecated(cand_prop)
    prop_deprecated_transition = not base_is_dep and cand_is_dep

    if prop_deprecated_transition:
        base_status = resolve_declared_entity_lifecycle(base_prop)
        base_status_str = base_status.value if base_status is not None else None
        changes.append(
            GovernanceChange(
                change_type=GovernanceChangeType.DEPRECATE,
                entity_type=GovernanceEntityType.PROPERTY,
                identity=prop_ident,
                path=prop_path,
                field="lifecycleStatus",
                before=base_status_str,
                after="deprecated",
                domain=GovernanceChangeDomain.LIFECYCLE,
            )
        )

    # Structural fields
    for field_name in sorted(ODCS_PROPERTY_STRUCTURAL_FIELDS):
        b_val = getattr(base_prop, field_name, None)
        c_val = getattr(cand_prop, field_name, None)
        if _to_json_compatible(b_val) != _to_json_compatible(c_val):
            changes.append(
                GovernanceChange(
                    change_type=GovernanceChangeType.MODIFY,
                    entity_type=GovernanceEntityType.PROPERTY,
                    identity=prop_ident,
                    path=f"{prop_path}.{field_name}",
                    field=field_name,
                    before=_to_json_compatible(b_val),
                    after=_to_json_compatible(c_val),
                    domain=GovernanceChangeDomain.STRUCTURE,
                )
            )

    # Enum / enumValues
    base_enums = sorted(_enum_values(base_prop))
    cand_enums = sorted(_enum_values(cand_prop))
    if base_enums != cand_enums:
        changes.append(
            GovernanceChange(
                change_type=GovernanceChangeType.MODIFY,
                entity_type=GovernanceEntityType.PROPERTY,
                identity=prop_ident,
                path=f"{prop_path}.enum",
                field="enum",
                before=base_enums or None,
                after=cand_enums or None,
                domain=GovernanceChangeDomain.STRUCTURE,
            )
        )

    # Metadata fields and dynamic model fields
    prop_metadata_fields = sorted(
        ODCS_PROPERTY_METADATA_FIELDS
        | (set(SchemaProperty.model_fields) - ODCS_PROPERTY_HANDLED_FIELDS)
    )
    for field_name in prop_metadata_fields:
        b_val = getattr(base_prop, field_name, None)
        c_val = getattr(cand_prop, field_name, None)
        if _to_json_compatible(b_val) != _to_json_compatible(c_val):
            changes.append(
                GovernanceChange(
                    change_type=GovernanceChangeType.MODIFY,
                    entity_type=GovernanceEntityType.PROPERTY,
                    identity=prop_ident,
                    path=f"{prop_path}.{field_name}",
                    field=field_name,
                    before=_to_json_compatible(b_val),
                    after=_to_json_compatible(c_val),
                    domain=GovernanceChangeDomain.METADATA,
                )
            )

    # Tags
    base_tags = [t for t in (base_prop.tags or [])]
    cand_tags = [t for t in (cand_prop.tags or [])]
    if prop_deprecated_transition:
        cand_tags = [t for t in cand_tags if t != "deprecated"]
    if sorted(base_tags) != sorted(cand_tags):
        changes.append(
            GovernanceChange(
                change_type=GovernanceChangeType.MODIFY,
                entity_type=GovernanceEntityType.PROPERTY,
                identity=prop_ident,
                path=f"{prop_path}.tags",
                field="tags",
                before=sorted(base_tags) or None,
                after=sorted(cand_tags) or None,
                domain=GovernanceChangeDomain.METADATA,
            )
        )

    # Custom properties
    changes.extend(
        _compare_custom_properties(
            identity=prop_ident,
            path=f"{prop_path}.customProperties",
            base_props=base_prop.customProperties,
            cand_props=cand_prop.customProperties,
            is_deprecated_transition=prop_deprecated_transition,
            entity_type=GovernanceEntityType.PROPERTY,
        )
    )

    # Nested struct properties
    if base_prop.properties or cand_prop.properties:
        changes.extend(
            _compare_properties(
                schema_id=schema_id,
                ancestry=prop_ident,
                base_props=base_prop.properties or [],
                cand_props=cand_prop.properties or [],
                parent_path=prop_path,
            )
        )

    # Array items property (single child object)
    if base_prop.items or cand_prop.items:
        if base_prop.items is None and cand_prop.items is not None:
            changes.append(
                GovernanceChange(
                    change_type=GovernanceChangeType.ADD,
                    entity_type=GovernanceEntityType.PROPERTY,
                    identity=(*prop_ident, "items"),
                    path=f"{prop_path}.items",
                    before=None,
                    after=_to_json_compatible(cand_prop.items),
                    domain=GovernanceChangeDomain.STRUCTURE,
                )
            )
        elif base_prop.items is not None and cand_prop.items is None:
            changes.append(
                GovernanceChange(
                    change_type=GovernanceChangeType.REMOVE,
                    entity_type=GovernanceEntityType.PROPERTY,
                    identity=(*prop_ident, "items"),
                    path=f"{prop_path}.items",
                    before=_to_json_compatible(base_prop.items),
                    after=None,
                    domain=GovernanceChangeDomain.STRUCTURE,
                )
            )
        elif base_prop.items is not None and cand_prop.items is not None:
            changes.extend(
                _compare_single_property_direct(
                    schema_id=schema_id,
                    prop_ident=(*prop_ident, "items"),
                    prop_path=f"{prop_path}.items",
                    base_prop=base_prop.items,
                    cand_prop=cand_prop.items,
                )
            )

    return changes


def _walk_all_properties(
    schema_id: str,
    properties: list[SchemaProperty] | None,
    ancestry: tuple[str, ...] | None = None,
    parent_path: str | None = None,
) -> list[tuple[tuple[str, ...], str, SchemaProperty]]:
    """Recursively walk all properties and array items, yielding (ancestry, path, property)."""
    results: list[tuple[tuple[str, ...], str, SchemaProperty]] = []
    if not properties:
        return results

    anc = ancestry or (schema_id,)
    base_path = parent_path or f"schema[{schema_id}]"

    for prop in properties:
        p_name = normalize_identity_name(getattr(prop, "name", None) or "item", "Property")
        prop_anc = (*anc, p_name)
        prop_path = f"{base_path}.properties[{p_name}]"
        results.append((prop_anc, prop_path, prop))

        if prop.properties:
            results.extend(
                _walk_all_properties(
                    schema_id,
                    prop.properties,
                    ancestry=prop_anc,
                    parent_path=prop_path,
                )
            )

        if prop.items:
            item_anc = (*prop_anc, "items")
            item_path = f"{prop_path}.items"
            results.append((item_anc, item_path, prop.items))
            if prop.items.properties:
                results.extend(
                    _walk_all_properties(
                        schema_id,
                        prop.items.properties,
                        ancestry=item_anc,
                        parent_path=item_path,
                    )
                )
            if prop.items.items:
                results.extend(
                    _walk_all_properties(
                        schema_id,
                        [prop.items.items],
                        ancestry=item_anc,
                        parent_path=item_path,
                    )
                )

    return results


def _compare_custom_properties(
    *,
    identity: tuple[str, ...],
    path: str,
    base_props: list[CustomProperty] | None,
    cand_props: list[CustomProperty] | None,
    is_deprecated_transition: bool,
    entity_type: GovernanceEntityType,
) -> list[GovernanceChange]:
    changes: list[GovernanceChange] = []
    base_dict = {
        str(cp.property): cp.value
        for cp in (base_props or [])
        if cp.property is not None
    }
    cand_dict = {
        str(cp.property): cp.value
        for cp in (cand_props or [])
        if cp.property is not None
    }

    # Suppress companion metadata when deprecating
    suppressed_keys = {"lifecycleStatus", "deprecationDate", "semapact.removed"} if is_deprecated_transition else set()

    for key in sorted(set(base_dict) | set(cand_dict)):
        if key in suppressed_keys:
            continue
        b_val = base_dict.get(key)
        c_val = cand_dict.get(key)
        if b_val != c_val:
            domain = GovernanceChangeDomain.LIFECYCLE if key.strip().lower() == "lifecyclestatus" else GovernanceChangeDomain.METADATA
            ch_type = (
                GovernanceChangeType.ADD
                if b_val is None
                else (GovernanceChangeType.REMOVE if c_val is None else GovernanceChangeType.MODIFY)
            )
            changes.append(
                GovernanceChange(
                    change_type=ch_type,
                    entity_type=entity_type,
                    identity=identity,
                    path=f"{path}[{key}]",
                    field=f"customProperties.{key}",
                    before=_to_json_compatible(b_val),
                    after=_to_json_compatible(c_val),
                    domain=domain,
                )
            )

    return changes


def _analyze_relationships(
    base_contract: OpenDataContractStandard,
    candidate_contract: OpenDataContractStandard,
) -> list[GovernanceChange]:
    changes: list[GovernanceChange] = []
    base_rels = _extract_all_relationships(base_contract)
    cand_rels = _extract_all_relationships(candidate_contract)

    for rel_key in sorted(set(cand_rels) - set(base_rels)):
        rel_info = cand_rels[rel_key]
        changes.append(
            GovernanceChange(
                change_type=GovernanceChangeType.ADD,
                entity_type=GovernanceEntityType.RELATIONSHIP,
                identity=rel_info["identity"],
                path=rel_info["path"],
                before=None,
                after=rel_info["snapshot"],
                domain=GovernanceChangeDomain.RELATIONSHIP,
            )
        )

    for rel_key in sorted(set(base_rels) - set(cand_rels)):
        rel_info = base_rels[rel_key]
        changes.append(
            GovernanceChange(
                change_type=GovernanceChangeType.REMOVE,
                entity_type=GovernanceEntityType.RELATIONSHIP,
                identity=rel_info["identity"],
                path=rel_info["path"],
                before=rel_info["snapshot"],
                after=None,
                domain=GovernanceChangeDomain.RELATIONSHIP,
            )
        )

    return changes


def _extract_all_relationships(
    contract: OpenDataContractStandard,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    schema_index = build_schema_index(contract)

    for schema_id, schema_obj in schema_index.items():
        # Schema level relationships
        if schema_obj.relationships:
            for rel in schema_obj.relationships:
                rel_type = str(getattr(rel, "type", "") or "foreignKey")
                from_val = getattr(rel, "from_", None) or getattr(rel, "from", None) or ""
                to_val = getattr(rel, "to", None) or ""
                from_str = normalize_endpoint_value(from_val)
                to_str = normalize_endpoint_value(to_val)
                rel_hash = f"{rel_type}:{from_str}->{to_str}"
                key = f"schema:{schema_id}:{rel_hash}"
                result[key] = {
                    "schema_id": schema_id,
                    "identity": (schema_id, rel_hash),
                    "path": f"schema[{schema_id}].relationships",
                    "snapshot": _to_json_compatible(rel),
                }

        # Recursive property level relationships (top-level, nested, and items)
        for prop_anc, prop_path, prop_obj in _walk_all_properties(schema_id, schema_obj.properties or []):
            if prop_obj.relationships:
                for rel in prop_obj.relationships:
                    rel_type = str(getattr(rel, "type", "") or "foreignKey")
                    to_val = getattr(rel, "to", None) or ""
                    from_str = ".".join(prop_anc)
                    to_str = normalize_endpoint_value(to_val)
                    rel_hash = f"{rel_type}:{from_str}->{to_str}"
                    key = f"prop:{'.'.join(prop_anc)}:{rel_hash}"
                    result[key] = {
                        "schema_id": schema_id,
                        "identity": (*prop_anc, rel_hash),
                        "path": f"{prop_path}.relationships",
                        "snapshot": _to_json_compatible(rel),
                    }

    return result


def _analyze_quality_rules(
    base_contract: OpenDataContractStandard,
    candidate_contract: OpenDataContractStandard,
) -> list[GovernanceChange]:
    changes: list[GovernanceChange] = []
    base_rules = _extract_all_quality_rules(base_contract)
    cand_rules = _extract_all_quality_rules(candidate_contract)

    for rule_key in sorted(set(cand_rules) - set(base_rules)):
        rule_info = cand_rules[rule_key]
        changes.append(
            GovernanceChange(
                change_type=GovernanceChangeType.ADD,
                entity_type=GovernanceEntityType.QUALITY,
                identity=rule_info["identity"],
                path=rule_info["path"],
                before=None,
                after=rule_info["snapshot"],
                domain=GovernanceChangeDomain.QUALITY,
            )
        )

    for rule_key in sorted(set(base_rules) - set(cand_rules)):
        rule_info = base_rules[rule_key]
        changes.append(
            GovernanceChange(
                change_type=GovernanceChangeType.REMOVE,
                entity_type=GovernanceEntityType.QUALITY,
                identity=rule_info["identity"],
                path=rule_info["path"],
                before=rule_info["snapshot"],
                after=None,
                domain=GovernanceChangeDomain.QUALITY,
            )
        )

    for rule_key in sorted(set(base_rules) & set(cand_rules)):
        base_info = base_rules[rule_key]
        cand_info = cand_rules[rule_key]
        if base_info["snapshot"] != cand_info["snapshot"]:
            changes.append(
                GovernanceChange(
                    change_type=GovernanceChangeType.MODIFY,
                    entity_type=GovernanceEntityType.QUALITY,
                    identity=base_info["identity"],
                    path=base_info["path"],
                    before=base_info["snapshot"],
                    after=cand_info["snapshot"],
                    domain=GovernanceChangeDomain.QUALITY,
                )
            )

    return changes


def _quality_rule_identifier(rule: Any, idx: int) -> str:
    r_id = getattr(rule, "id", None)
    if r_id:
        return str(r_id).strip().lower()
    r_name = getattr(rule, "name", None)
    if r_name:
        return str(r_name).strip().lower()
    r_rule = getattr(rule, "rule", None)
    if r_rule:
        return str(r_rule).strip().lower()
    r_type = getattr(rule, "type", None)
    if r_type:
        return f"{str(r_type).strip().lower()}_{idx}"
    return f"rule_{idx}"


def _extract_all_quality_rules(
    contract: OpenDataContractStandard,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}

    # Contract level quality
    contract_quality = getattr(contract, "quality", None)
    if contract_quality:
        for idx, rule in enumerate(contract_quality):
            r_name = _quality_rule_identifier(rule, idx)
            key = f"contract:{r_name}"
            result[key] = {
                "identity": (str(contract.id or ""), r_name),
                "path": f"quality[{r_name}]",
                "snapshot": _to_json_compatible(rule),
            }

    # Schema & recursive property level quality
    schema_index = build_schema_index(contract)
    for schema_id, schema_obj in schema_index.items():
        if schema_obj.quality:
            for idx, rule in enumerate(schema_obj.quality):
                r_name = _quality_rule_identifier(rule, idx)
                key = f"schema:{schema_id}:{r_name}"
                result[key] = {
                    "identity": (schema_id, r_name),
                    "path": f"schema[{schema_id}].quality[{r_name}]",
                    "snapshot": _to_json_compatible(rule),
                }

        # Recursive properties & items
        for prop_anc, prop_path, prop_obj in _walk_all_properties(schema_id, schema_obj.properties or []):
            if prop_obj.quality:
                for idx, rule in enumerate(prop_obj.quality):
                    r_name = _quality_rule_identifier(rule, idx)
                    key = f"prop:{'.'.join(prop_anc)}:{r_name}"
                    result[key] = {
                        "identity": (*prop_anc, r_name),
                        "path": f"{prop_path}.quality[{r_name}]",
                        "snapshot": _to_json_compatible(rule),
                    }

    return result


def _enum_values(prop: SchemaProperty) -> set[str]:
    for key in ("enum", "enumValues"):
        values = getattr(prop, key, None)
        if isinstance(values, list):
            return {str(item) for item in values}
    return set()
