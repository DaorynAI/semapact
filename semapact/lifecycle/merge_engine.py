import re
import logging
from copy import deepcopy
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any, Iterable

from open_data_contract_standard.model import (
    CustomProperty,
    DataQuality,
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)
from semapact.lifecycle.helpers import (
    schema_object_identity,
    normalize_identity_name,
)

LOGGER = logging.getLogger(__name__)

BUSINESS_METADATA_KEYS = {
    "description",
    "businessName",
    "classification",
    "tags",
    "examples",
    "lifecycleStatus",
    "status",
}
# Quality rules are lifecycle metadata and must be merged using name-based lifecycle semantics.

REMOVED_FLAG = {"property": "semapact.removed", "value": "true"}
LIFECYCLE_STATUS_PROPERTY = "lifecycleStatus"
DEPRECATED_LIFECYCLE_VALUE = "deprecated"

# Technical fields that must be overwritten from imported source for matching properties.
PROPERTY_OVERWRITE_FIELDS: tuple[str, ...] = (
    "logicalType",
    "physicalType",
    "physicalName",
    "partitioned",
    "partitionKeyPosition",
    "description",
    "transformLogic",
    "transformSourceObjects",
    "transformDescription",
    "logicalTypeOptions",
    "required",
    "primaryKey",
    "primaryKeyPosition",
    "unique",
    "encryptedName",
)

# Technical fields that must be overwritten from imported source for matching schemas.
SCHEMA_OBJECT_OVERWRITE_FIELDS: tuple[str, ...] = (
    "physicalType",
    "physicalName",
    "logicalType",
    "dataGranularityDescription",
    "description",
)
OdcModel = OpenDataContractStandard


class MergeConflictError(Exception):
    """Raised when a fatal conflict prevents any merge attempt (e.g., retired contract)."""

    pass


@dataclass(slots=True)
class MergeConflict:
    """Represents a merge conflict between source and target contracts."""

    path: str | None = None
    rule: str | None = None
    base_value: Any = None
    business_value: Any = None
    schema_id: str | None = None
    property_name: str | None = None
    message: str | None = None


@dataclass(slots=True)
class MergeResult:
    """Merge result payload."""

    contract: OpenDataContractStandard
    conflicts: list[MergeConflict] = field(default_factory=list)


@dataclass(slots=True)
class MergeAnalysis:
    """Analyze phase output used by apply phase."""

    conflicts: list[MergeConflict] = field(default_factory=list)
    deprecated_schemas: set[str] = field(default_factory=set)
    deprecated_properties: dict[str, set[str]] = field(default_factory=dict)


@dataclass(slots=True)
class ContractMergeEngine:
    """Merge ODCS contracts while preserving business metadata and quality rules."""

    def analyze(
        self,
        base_contract: OpenDataContractStandard,
        business_contract: OpenDataContractStandard,
    ) -> MergeAnalysis:
        """Analyze a source contract against the governed business contract."""
        source_model = _to_odcs_model(base_contract)
        target_model = _to_odcs_model(business_contract)

        LOGGER.info(
            "Starting merge for contract: %s (version: %s)",
            target_model.id,
            target_model.version,
        )

        if _is_retired_contract(target_model):
            LOGGER.error("Merge failed: contract %s is retired", target_model.id)
            raise MergeConflictError("Retired contract cannot be modified")

        return self._analyze_merge(target_model=target_model, source_model=source_model)

    def merge(
        self,
        base_contract: OpenDataContractStandard,
        business_contract: OpenDataContractStandard,
        *,
        fail_on_conflict: bool = False,
    ) -> MergeResult:
        # source_model = newly generated technical contract
        source_model = _to_odcs_model(base_contract)
        target_model = _to_odcs_model(business_contract)
        analysis = self.analyze(source_model, target_model)
        if fail_on_conflict and analysis.conflicts:
            rules = ", ".join({c.rule for c in analysis.conflicts if c.rule})
            from semapact.exceptions import MergeConflictError

            raise MergeConflictError(f"Merge conflicts detected: {rules}")

        merged_model = self._merge_odcs_models(
            target_model=target_model,
            source_model=source_model,
            analysis=analysis,
        )
        LOGGER.info(
            "Successfully merged contract %s. Deprecated %d schemas, %d properties.",
            target_model.id,
            len(analysis.deprecated_schemas),
            len(analysis.deprecated_properties),
        )
        return MergeResult(contract=merged_model, conflicts=analysis.conflicts)

    def detect_conflicts(
        self,
        base_contract: OpenDataContractStandard,
        business_contract: OpenDataContractStandard,
    ) -> list[MergeConflict]:
        return self.analyze(base_contract, business_contract).conflicts

    def _analyze_merge(
        self,
        *,
        target_model: OpenDataContractStandard,
        source_model: OpenDataContractStandard,
    ) -> MergeAnalysis:
        analysis = MergeAnalysis()

        # Lifecycle gating: breaking checks and auto-deprecation apply only to active contracts.
        if not _is_active_contract(target_model):
            return analysis

        existing_schema = {
            _schema_object_id(schema): schema
            for schema in (target_model.schema_ or [])
            if _schema_object_id(schema)
        }
        imported_schema = {
            _schema_object_id(schema): schema
            for schema in (source_model.schema_ or [])
            if _schema_object_id(schema)
        }

        for schema_id, existing_schema_obj in existing_schema.items():
            if _is_draft_or_deprecated(existing_schema_obj):
                continue

            imported_schema_obj = imported_schema.get(schema_id)
            if imported_schema_obj is None:
                analysis.deprecated_schemas.add(schema_id)
                continue
            if _is_draft_or_deprecated(imported_schema_obj):
                continue

            existing_props = {
                _property_id(prop): prop
                for prop in (existing_schema_obj.properties or [])
                if _property_id(prop)
            }
            imported_props = {
                _property_id(prop): prop
                for prop in (imported_schema_obj.properties or [])
                if _property_id(prop)
            }

            for prop_id, existing_prop in existing_props.items():
                if _is_draft_or_deprecated(existing_prop):
                    continue

                imported_prop = imported_props.get(prop_id)
                if imported_prop is None:
                    analysis.deprecated_properties.setdefault(schema_id, set()).add(
                        prop_id
                    )
                    continue
                if _is_draft_or_deprecated(imported_prop):
                    continue

                path = f"schema[{schema_id}].properties[{prop_id}]"
                analysis.conflicts.extend(
                    self._property_conflicts(path, imported_prop, existing_prop)
                )

        return analysis

    def _property_conflicts(
        self, path: str, imported_prop: SchemaProperty, existing_prop: SchemaProperty
    ) -> list[MergeConflict]:
        conflicts: list[MergeConflict] = []
        imported_logical = imported_prop.logicalType
        existing_logical = existing_prop.logicalType
        imported_physical = imported_prop.physicalType
        existing_physical = existing_prop.physicalType

        if _value_conflict(imported_logical, existing_logical):
            conflicts.append(
                MergeConflict(
                    path=f"{path}.logicalType",
                    rule="logical_type_mismatch",
                    base_value=imported_logical,
                    business_value=existing_logical,
                )
            )

        if _is_decimal_physical_type(imported_physical) and _is_decimal_physical_type(
            existing_physical
        ):
            precision_change = _decimal_precision_reduction(
                imported_physical, existing_physical
            )
            scale_change = _decimal_scale_reduction(
                imported_physical, existing_physical
            )
            if precision_change:
                conflicts.append(
                    MergeConflict(
                        path=f"{path}.physicalType",
                        rule="decimal_precision_reduction",
                        base_value=imported_physical,
                        business_value=existing_physical,
                    )
                )
            if scale_change:
                conflicts.append(
                    MergeConflict(
                        path=f"{path}.physicalType",
                        rule="decimal_scale_reduction",
                        base_value=imported_physical,
                        business_value=existing_physical,
                    )
                )
        elif _value_conflict(imported_physical, existing_physical):
            conflicts.append(
                MergeConflict(
                    path=f"{path}.physicalType",
                    rule="physical_type_change",
                    base_value=imported_physical,
                    business_value=existing_physical,
                )
            )

        imported_required = imported_prop.required
        existing_required = existing_prop.required
        if imported_required is True and existing_required is not True:
            conflicts.append(
                MergeConflict(
                    path=f"{path}.required",
                    rule="required_tightening",
                    base_value=imported_required,
                    business_value=existing_required,
                )
            )

        return conflicts

    def _merge_odcs_models(
        self,
        *,
        target_model: OpenDataContractStandard,
        source_model: OpenDataContractStandard,
        analysis: MergeAnalysis,
    ) -> OpenDataContractStandard:
        merged = target_model.model_copy(deep=True)

        # source_model = newly generated technical contract
        # target_model = existing business contract in Git
        # Technical updates come from source model at contract level, except:
        # - schema/quality/customProperties, which are merged separately
        # - root id/version, which stay anchored to the governed contract
        for field_name in OpenDataContractStandard.model_fields:
            if field_name in {
                "id",
                "version",
                "schema_",
                "quality",
                "customProperties",
            }:
                continue
            source_value = getattr(source_model, field_name, None)
            if source_value is not None:
                setattr(merged, field_name, deepcopy(source_value))

        # Governance metadata from target contract remains source of truth.
        for metadata_key in BUSINESS_METADATA_KEYS:
            if not hasattr(merged, metadata_key):
                continue
            target_value = getattr(target_model, metadata_key, None)
            if target_value is not None:
                setattr(merged, metadata_key, deepcopy(target_value))

        # customProperties are lifecycle metadata and must always be key-merged, never overwritten.
        merged.customProperties = _merge_custom_properties_models(
            target_model.customProperties,
            source_model.customProperties,
        )
        # Quality rules represent governance lifecycle state and must be merged by rule identity.
        if hasattr(merged, "quality"):
            merged.quality = _combine_quality_rules_models(  # type: ignore[attr-defined]
                getattr(target_model, "quality", None),
                getattr(source_model, "quality", None),
            )

        # Two-phase merge: analyze first (conflicts/deprecations), then apply deterministic updates.
        merged.schema_ = _merge_schema_objects_models(
            existing_schema=target_model.schema_ or [],
            imported_schema=source_model.schema_ or [],
            analysis=analysis,
        )
        return merged


def _merge_schema_objects_models(
    existing_schema: list[SchemaObject],
    imported_schema: list[SchemaObject],
    analysis: MergeAnalysis,
) -> list[SchemaObject]:
    existing_index = {
        _schema_object_id(obj): obj for obj in existing_schema if _schema_object_id(obj)
    }
    imported_index = {
        _schema_object_id(obj): obj for obj in imported_schema if _schema_object_id(obj)
    }

    merged_schema: list[SchemaObject] = []
    # All ordering must be identity-based to ensure stable Git diffs.
    for existing_id in sorted(existing_index):
        existing_obj = existing_index[existing_id]
        imported_obj = imported_index.get(existing_id)
        if imported_obj is None:
            if existing_id in analysis.deprecated_schemas:
                merged_schema.append(_deprecate_schema_model(existing_obj))
            else:
                merged_schema.append(existing_obj.model_copy(deep=True))
            continue
        merged_schema.append(
            _merge_schema_object_models(
                existing_obj=existing_obj,
                imported_obj=imported_obj,
                deprecated_property_ids=analysis.deprecated_properties.get(
                    existing_id, set()
                ),
            )
        )

    for imported_id in sorted(imported_index):
        if imported_id in existing_index:
            continue
        merged_schema.append(imported_index[imported_id].model_copy(deep=True))

    # Final deterministic ordering by canonical ODCS identity (`name`).
    merged_schema.sort(key=_schema_object_id)
    return merged_schema


def _merge_schema_object_models(
    existing_obj: SchemaObject,
    imported_obj: SchemaObject,
    deprecated_property_ids: set[str],
) -> SchemaObject:
    merged_obj = existing_obj.model_copy(deep=True)

    # Schema-level lifecycle metadata is merged; schema identity is ODCS `name`.
    for field_name in SCHEMA_OBJECT_OVERWRITE_FIELDS:
        _copy_if_provided(merged_obj, imported_obj, field_name)
        
    merged_obj.relationships = _merge_relationships_models(
        getattr(existing_obj, "relationships", None),
        getattr(imported_obj, "relationships", None),
    )
    merged_obj.customProperties = _merge_custom_properties_models(
        existing_obj.customProperties,
        imported_obj.customProperties,
    )
    merged_obj.quality = _combine_quality_rules_models(
        existing_obj.quality, imported_obj.quality
    )
    merged_obj.properties = _merge_properties_models(
        existing_props=existing_obj.properties or [],
        imported_props=imported_obj.properties or [],
        deprecated_property_ids=deprecated_property_ids,
    )
    return merged_obj


def _merge_properties_models(
    existing_props: list[SchemaProperty],
    imported_props: list[SchemaProperty],
    deprecated_property_ids: set[str],
) -> list[SchemaProperty]:
    existing_index = {
        _property_id(prop): prop for prop in existing_props if _property_id(prop)
    }
    imported_index = {
        _property_id(prop): prop for prop in imported_props if _property_id(prop)
    }

    merged_props: list[SchemaProperty] = []
    # All ordering must be identity-based to ensure stable Git diffs.
    for existing_id in sorted(existing_index):
        existing_prop = existing_index[existing_id]
        imported_prop = imported_index.get(existing_id)
        if imported_prop is None:
            if existing_id in deprecated_property_ids:
                merged_props.append(_deprecate_property_model(existing_prop))
            else:
                merged_props.append(existing_prop.model_copy(deep=True))
            continue

        merged_props.append(
            _merge_matching_property_models(
                existing_prop=existing_prop,
                imported_prop=imported_prop,
            )
        )

    for imported_id in sorted(imported_index):
        if imported_id in existing_index:
            continue
        merged_props.append(imported_index[imported_id].model_copy(deep=True))

    # Final deterministic ordering by canonical ODCS identity (`name`).
    merged_props.sort(key=_property_id)
    return merged_props


def _merge_matching_property_models(
    existing_prop: SchemaProperty, imported_prop: SchemaProperty
) -> SchemaProperty:
    merged_prop = existing_prop.model_copy(deep=True)
    existing_status = _resolve_lifecycle_status(existing_prop)

    if existing_status == DEPRECATED_LIFECYCLE_VALUE:
        # Prevent implicit reactivation of deprecated fields.
        _copy_if_provided(merged_prop, imported_prop, "description")
        _copy_if_provided(merged_prop, imported_prop, "tags")
        merged_prop.customProperties = _merge_custom_properties_models(
            existing_prop.customProperties,
            imported_prop.customProperties,
        )
        merged_prop.customProperties = _merge_custom_properties_models(
            merged_prop.customProperties,
            [
                {
                    "property": LIFECYCLE_STATUS_PROPERTY,
                    "value": DEPRECATED_LIFECYCLE_VALUE,
                }
            ],
        )
        merged_prop.tags = _add_deprecated_tag(merged_prop.tags)
        merged_prop.quality = _combine_quality_rules_models(
            existing_prop.quality, imported_prop.quality
        )
        merged_prop.customProperties = _sort_custom_properties(
            merged_prop.customProperties
        )
        return merged_prop

    # Matching-property updates overwrite technical fields from imported source.
    for field_name in PROPERTY_OVERWRITE_FIELDS:
        _copy_if_provided(merged_prop, imported_prop, field_name)
    merged_prop.relationships = _merge_relationships_models(
        getattr(existing_prop, "relationships", None),
        getattr(imported_prop, "relationships", None),
    )
    merged_prop.quality = _combine_quality_rules_models(
        existing_prop.quality, imported_prop.quality
    )
    merged_prop.customProperties = _merge_custom_properties_models(
        existing_prop.customProperties, imported_prop.customProperties
    )
    merged_prop.customProperties = _sort_custom_properties(merged_prop.customProperties)

    if existing_prop.properties or imported_prop.properties:
        merged_prop.properties = _merge_properties_models(
            existing_props=existing_prop.properties or [],
            imported_props=imported_prop.properties or [],
            deprecated_property_ids=set(),
        )

    if existing_prop.items or imported_prop.items:
        if existing_prop.items and imported_prop.items:
            merged_prop.items = _merge_matching_property_models(
                existing_prop=existing_prop.items,
                imported_prop=imported_prop.items,
            )
        elif imported_prop.items:
            merged_prop.items = imported_prop.items.model_copy(deep=True)

    return merged_prop


def _merge_relationships_models(existing: Any, imported: Any) -> list[Any] | None:
    merged: list[Any] = []

    if existing:
        for rel in existing:
            rel_type = str(getattr(rel, "type", "") or "").strip().upper()
            if rel_type not in ("FOREIGN_KEY", "FOREIGNKEY"):
                merged.append(rel.model_copy(deep=True))

    if imported:
        for rel in imported:
            rel_type = str(getattr(rel, "type", "") or "").strip().upper()
            if rel_type in ("FOREIGN_KEY", "FOREIGNKEY"):
                merged.append(rel.model_copy(deep=True))

    if not merged:
        return None

    merged.sort(
        key=lambda r: (
            str(getattr(r, "type", "") or ""),
            str(getattr(r, "to", "") or ""),
        )
    )
    return merged


def _deprecate_schema_model(entity: SchemaObject) -> SchemaObject:
    removed = entity.model_copy(deep=True)
    removed.customProperties = _merge_custom_properties_models(
        removed.customProperties,
        [
            REMOVED_FLAG,
            {
                "property": LIFECYCLE_STATUS_PROPERTY,
                "value": DEPRECATED_LIFECYCLE_VALUE,
            },
        ],
    )
    removed.tags = _add_deprecated_tag(removed.tags)
    return removed


def _deprecate_property_model(entity: SchemaProperty) -> SchemaProperty:
    removed = entity.model_copy(deep=True)
    deprecation_date = _custom_property_value(
        removed.customProperties, "deprecationDate"
    )
    deprecation_items: list[dict[str, str]] = [
        REMOVED_FLAG,
        {"property": LIFECYCLE_STATUS_PROPERTY, "value": DEPRECATED_LIFECYCLE_VALUE},
    ]
    if deprecation_date is None:
        deprecation_items.append(
            {
                "property": "deprecationDate",
                "value": datetime.now(timezone.utc).date().isoformat(),
            }
        )
    removed.customProperties = _merge_custom_properties_models(
        removed.customProperties,
        deprecation_items,
    )
    removed.tags = _add_deprecated_tag(removed.tags)
    return removed


def _copy_if_provided(target: Any, source: Any, field_name: str) -> None:
    source_fields: set[str] = getattr(source, "model_fields_set", set())
    source_value = getattr(source, field_name, None)
    if field_name in source_fields or source_value is not None:
        setattr(target, field_name, deepcopy(source_value))


def _sort_custom_properties(
    custom_properties: list[CustomProperty] | None,
) -> list[CustomProperty] | None:
    normalized = _normalize_custom_property_models(custom_properties)
    if not normalized:
        return None
    normalized.sort(key=_custom_property_sort_key)
    return normalized


def _add_deprecated_tag(tags: list[str] | None) -> list[str]:
    if not isinstance(tags, list):
        return ["deprecated"]
    normalized = [str(tag) for tag in tags]
    if "deprecated" not in normalized:
        normalized.append("deprecated")
    normalized.sort()
    return normalized


def _schema_object_id(schema_obj: SchemaObject) -> str:
    return schema_object_identity(schema_obj)


def _property_id(prop: SchemaProperty) -> str:
    return normalize_identity_name(prop.name, "Property")


def _is_active_contract(contract: OpenDataContractStandard) -> bool:
    return _resolve_lifecycle_status(contract) == "active"


def _is_retired_contract(contract: OdcModel) -> bool:
    status_value = getattr(contract, "status", None)
    if status_value is not None:
        return _normalize_status(status_value, default="draft") == "retired"
    custom_status = _custom_property_value(
        getattr(contract, "customProperties", None), LIFECYCLE_STATUS_PROPERTY
    )
    if custom_status is None:
        return False
    return _normalize_status(custom_status, default="draft") == "retired"


def _is_draft_or_deprecated(entity: Any) -> bool:
    lifecycle_status = _resolve_lifecycle_status(entity)
    return lifecycle_status in {"draft", "deprecated"}


def _resolve_lifecycle_status(obj: Any) -> str:
    status_value = getattr(obj, "status", None)
    if status_value is not None:
        return _normalize_status(status_value, default="draft")
    custom_status = _custom_property_value(
        getattr(obj, "customProperties", None), LIFECYCLE_STATUS_PROPERTY
    )
    if custom_status is not None:
        return _normalize_status(custom_status, default="draft")
    return "draft"


def _custom_property_value(custom_properties: Any, key: str) -> str | None:
    normalized_items = _normalize_custom_property_models(custom_properties)
    normalized_key = key.strip().lower()
    for item in normalized_items:
        item_key = str(item.property or "").strip().lower()
        if item_key == normalized_key:
            return str(item.value)
    return None


def _normalize_status(value: Any, *, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip().lower()
    return text or default


def _has_removed_flag(custom_properties: Iterable[dict[str, Any]]) -> bool:
    for item in custom_properties:
        if (
            item.get("property") == REMOVED_FLAG["property"]
            and str(item.get("value")).lower() == "true"
        ):
            return True
    return False


def _value_conflict(base_value: Any, business_value: Any) -> bool:
    return (
        base_value is not None
        and business_value is not None
        and base_value != business_value
    )


def _is_decimal_physical_type(physical_type: Any) -> bool:
    return _decimal_precision_scale(physical_type) is not None


def _decimal_precision_reduction(
    imported_physical_type: Any, existing_physical_type: Any
) -> bool:
    imported_ps = _decimal_precision_scale(imported_physical_type)
    existing_ps = _decimal_precision_scale(existing_physical_type)
    if imported_ps is None or existing_ps is None:
        return False
    return imported_ps[0] < existing_ps[0]


def _decimal_scale_reduction(
    imported_physical_type: Any, existing_physical_type: Any
) -> bool:
    imported_ps = _decimal_precision_scale(imported_physical_type)
    existing_ps = _decimal_precision_scale(existing_physical_type)
    if imported_ps is None or existing_ps is None:
        return False
    return imported_ps[1] < existing_ps[1]


def _decimal_precision_scale(physical_type: Any) -> tuple[int, int] | None:
    if not isinstance(physical_type, str):
        return None

    match = re.match(
        r"\s*decimal\((\d+)\s*,\s*(\d+)\)\s*", physical_type, re.IGNORECASE
    )
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _quality_rule_sort_key(rule: Any) -> str:
    return _quality_rule_name(rule)


def _quality_rule_name(rule: Any) -> str:
    return str(getattr(rule, "name", None) or "").strip().lower()


def _combine_quality_rules_models(*rule_sets: Any) -> list[DataQuality] | None:
    # Quality rules represent governance lifecycle state.
    named: dict[str, DataQuality] = {}
    unnamed: list[DataQuality] = []

    for rules in rule_sets:
        for rule in _normalize_quality_models(rules):
            rule_name = _quality_rule_name(rule)
            if rule_name:
                named[rule_name] = rule.model_copy(deep=True)
            else:
                unnamed.append(rule.model_copy(deep=True))

    merged = list(named.values()) + unnamed
    # Sorting must be based solely on identity to guarantee deterministic GitOps diffs.
    merged.sort(key=_quality_rule_sort_key)
    return merged or None


def _merge_custom_properties_models(
    existing: Any, imported: Any
) -> list[CustomProperty] | None:
    merged_index: dict[str, CustomProperty] = {}
    unnamed: list[CustomProperty] = []

    for item in _normalize_custom_property_models(existing):
        item_key = _custom_property_key(item)
        if item_key:
            merged_index[item_key] = item.model_copy(deep=True)
        else:
            unnamed.append(item.model_copy(deep=True))

    for item in _normalize_custom_property_models(imported):
        item_key = _custom_property_key(item)
        if item_key:
            merged_index[item_key] = item.model_copy(deep=True)
        else:
            unnamed.append(item.model_copy(deep=True))

    merged = list(merged_index.values()) + unnamed
    merged.sort(key=_custom_property_sort_key)
    return merged or None


def _normalize_quality_models(rules: Any) -> list[DataQuality]:
    if not isinstance(rules, list):
        return []

    normalized: list[DataQuality] = []
    for rule in rules:
        if isinstance(rule, DataQuality):
            normalized.append(rule)
        elif isinstance(rule, dict):
            normalized.append(DataQuality.model_validate(deepcopy(rule)))
    return normalized


def _normalize_custom_property_models(items: Any) -> list[CustomProperty]:
    if not isinstance(items, list):
        return []

    normalized: list[CustomProperty] = []
    for item in items:
        if isinstance(item, CustomProperty):
            normalized.append(item)
        elif isinstance(item, dict):
            normalized.append(CustomProperty.model_validate(deepcopy(item)))
    return normalized


def _custom_property_key(item: Any) -> str:
    return str(getattr(item, "property", None) or "").strip().lower()


def _custom_property_sort_key(item: Any) -> str:
    return _custom_property_key(item)


def _to_odcs_model(contract: OpenDataContractStandard) -> OpenDataContractStandard:
    # ContractMergeEngine is ODCS-only: always normalize to the canonical ODCS model.
    model = contract.model_copy(deep=True)
    _assert_supported_api_version(model.apiVersion)
    return model


def _assert_supported_api_version(api_version: Any) -> None:
    major_minor = _parse_api_major_minor(api_version)
    if major_minor is None:
        from semapact.exceptions import ValidationError

        raise ValidationError("Contract apiVersion must be set and in v3.0.0+ format")
    major, minor = major_minor
    if major < 3:
        from semapact.exceptions import ValidationError

        raise ValidationError(
            f"Unsupported apiVersion '{api_version}'. Only v3.0.0 and above are supported"
        )


def _parse_api_major_minor(api_version: Any) -> tuple[int, int] | None:
    if not isinstance(api_version, str):
        return None
    text = api_version.strip().lower()
    if not text:
        return None
    match = re.match(r"^v?(\d+)\.(\d+)(?:\.\d+)?$", text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))
