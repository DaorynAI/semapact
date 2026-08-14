"""Authoritative lifecycle status model and resolution for Open Data Contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from open_data_contract_standard.model import (
    CustomProperty,
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

LIFECYCLE_STATUS_PROPERTY = "lifecycleStatus"


class LifecycleStatus(StrEnum):
    """Canonical lifecycle status for data contracts, schemas, and properties."""

    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


def normalize_status(value: Any) -> LifecycleStatus:
    """Normalize status string to canonical LifecycleStatus enum.

    Supported values & aliases:
    - 'draft', 'proposed' -> LifecycleStatus.DRAFT
      (Note: 'proposed' is a read-only governance interpretation alias;
       SemaPact does not rewrite ODCS YAML status during resolution)
    - 'active' -> LifecycleStatus.ACTIVE
    - 'deprecated' -> LifecycleStatus.DEPRECATED
    - 'retired' -> LifecycleStatus.RETIRED

    Raises:
        ValueError: If value is None, empty, or an unsupported status string.
    """
    if value is None:
        raise ValueError("Lifecycle status value cannot be None")

    if isinstance(value, LifecycleStatus):
        return value

    text = str(value).strip().lower()
    if not text:
        raise ValueError("Lifecycle status value cannot be empty")

    if text in ("draft", "proposed"):
        return LifecycleStatus.DRAFT
    if text == "active":
        return LifecycleStatus.ACTIVE
    if text == "deprecated":
        return LifecycleStatus.DEPRECATED
    if text == "retired":
        return LifecycleStatus.RETIRED

    raise ValueError(f"Unknown lifecycle status: {value!r}")


def lifecycle_from_custom_properties(custom_properties: Any) -> LifecycleStatus | None:
    """Extract and parse lifecycleStatus from customProperties list.

    Supports both CustomProperty model instances and dict objects.
    """
    if not isinstance(custom_properties, list):
        return None

    normalized_key = LIFECYCLE_STATUS_PROPERTY.lower()
    for item in custom_properties:
        if isinstance(item, CustomProperty):
            key = (item.property or "").strip().lower()
            if key == normalized_key:
                if item.value is None or str(item.value).strip() == "":
                    return None
                try:
                    return normalize_status(item.value)
                except ValueError:
                    return None
        elif isinstance(item, dict):
            key = str(item.get("property") or "").strip().lower()
            if key == normalized_key:
                val = item.get("value")
                if val is None or str(val).strip() == "":
                    return None
                try:
                    return normalize_status(val)
                except ValueError:
                    return None
    return None


def resolve_contract_lifecycle(
    contract: OpenDataContractStandard,
) -> LifecycleStatus:
    """Resolve authoritative contract root lifecycle status.

    Fallback order:
    1. contract.status (ODCS native canonical root status)
    2. contract.customProperties.lifecycleStatus (legacy fallback)
    3. LifecycleStatus.DRAFT (canonical default)
    """
    if contract is None:
        return LifecycleStatus.DRAFT

    # 1. Native root status
    raw_status = contract.status
    if raw_status is not None and str(raw_status).strip() != "":
        try:
            return normalize_status(raw_status)
        except ValueError:
            return LifecycleStatus.DRAFT

    # 2. Legacy customProperties fallback
    declared = lifecycle_from_custom_properties(contract.customProperties)
    if declared is not None:
        return declared

    # 3. Canonical default
    return LifecycleStatus.DRAFT



def resolve_declared_entity_lifecycle(
    entity: SchemaObject | SchemaProperty,
) -> LifecycleStatus | None:
    """Extract declared lifecycleStatus annotation directly from entity customProperties."""
    if entity is None:
        return None
    return lifecycle_from_custom_properties(entity.customProperties)


def resolve_schema_lifecycle(
    schema_obj: SchemaObject,
    *,
    contract: OpenDataContractStandard,
) -> LifecycleStatus:
    """Resolve effective governance lifecycle status for a schema object.

    Rules:
    - If parent contract != ACTIVE -> parent contract effective status wins.
    - Else if schema has declared lifecycleStatus -> schema declared status.
    - Else -> ACTIVE.
    """
    contract_status = resolve_contract_lifecycle(contract)
    if contract_status is not LifecycleStatus.ACTIVE:
        return contract_status

    declared = resolve_declared_entity_lifecycle(schema_obj)
    if declared is not None:
        return declared

    return LifecycleStatus.ACTIVE


def resolve_property_lifecycle(
    prop: SchemaProperty,
    *,
    parent_lifecycle: LifecycleStatus,
) -> LifecycleStatus:
    """Resolve effective governance lifecycle status for a schema property or nested child.

    Rules:
    - If parent_lifecycle != ACTIVE -> parent_lifecycle wins.
    - Else if property has declared lifecycleStatus -> property declared status.
    - Else -> ACTIVE.
    """
    if parent_lifecycle is not LifecycleStatus.ACTIVE:
        return parent_lifecycle

    declared = resolve_declared_entity_lifecycle(prop)
    if declared is not None:
        return declared

    return LifecycleStatus.ACTIVE


def is_active_contract(contract: OpenDataContractStandard) -> bool:
    """Return True if contract-level effective lifecycle status is active."""
    return resolve_contract_lifecycle(contract) is LifecycleStatus.ACTIVE


def is_retired_contract(contract: OpenDataContractStandard) -> bool:
    """Return True if contract-level effective lifecycle status is retired."""
    return resolve_contract_lifecycle(contract) is LifecycleStatus.RETIRED


def participates_in_breaking_checks(
    effective_lifecycle: LifecycleStatus,
) -> bool:
    """Return True ONLY when effective governance lifecycle is ACTIVE."""
    return effective_lifecycle is LifecycleStatus.ACTIVE


def is_explicitly_deprecated(
    entity: SchemaObject | SchemaProperty,
) -> bool:
    """Return True if entity's own declared lifecycleStatus is DEPRECATED."""
    return resolve_declared_entity_lifecycle(entity) is LifecycleStatus.DEPRECATED
