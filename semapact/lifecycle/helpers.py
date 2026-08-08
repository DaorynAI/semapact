from __future__ import annotations

import re
from typing import Any

from open_data_contract_standard.model import CustomProperty, OpenDataContractStandard

ACTIVE_STATUSES = {"active"}
NON_BREAKING_LIFECYCLE_STATUSES = {"draft", "deprecated"}


def normalize_status(value: Any, default: str = "draft") -> str:
    """Normalize status-like values to lowercase strings."""
    if value is None:
        return default
    text = str(value).strip().lower()
    return text or default


def is_active_contract(contract: OpenDataContractStandard) -> bool:
    """Return True when contract-level status is active."""
    value = contract.status
    if not value:
        value = lifecycle_from_custom_properties(contract.customProperties)
    return normalize_status(value, default="draft") in ACTIVE_STATUSES


def allows_breaking_changes(entity: Any) -> bool:
    """Return True when entity lifecycle status permits non-breaking updates only."""
    value = getattr(entity, "lifecycleStatus", None)
    if value is None:
        value = lifecycle_from_custom_properties(
            getattr(entity, "customProperties", None)
        )
    lifecycle_status = normalize_status(value, default="active")
    return lifecycle_status not in NON_BREAKING_LIFECYCLE_STATUSES


def schema_items(contract: OpenDataContractStandard) -> list[Any]:
    """Return schema entries for the ODCS contract."""
    return list(contract.schema_ or [])


def lifecycle_from_custom_properties(custom_properties: Any) -> Any:
    """Extract lifecycleStatus from custom properties list.

    Supports both ``CustomProperty`` model instances and raw ``dict`` items.
    """
    if not isinstance(custom_properties, list):
        return None
    for item in custom_properties:
        if isinstance(item, CustomProperty):
            key = (item.property or "").strip().lower()
            if key == "lifecyclestatus":
                return item.value
        elif isinstance(item, dict):
            key = str(item.get("property") or "").strip().lower()
            if key == "lifecyclestatus":
                return item.get("value")
    return None


# Keep the old private name as an alias for backwards compatibility within
# the package.  New code should use ``lifecycle_from_custom_properties``.
_lifecycle_from_custom_properties = lifecycle_from_custom_properties


# ---------------------------------------------------------------------------
# Decimal precision / scale comparison helpers
# ---------------------------------------------------------------------------


def decimal_precision_reduction(
    imported_physical_type: Any, existing_physical_type: Any
) -> bool:
    """Return True when the imported decimal precision is narrower than existing."""
    imported_ps = _decimal_precision_scale(imported_physical_type)
    existing_ps = _decimal_precision_scale(existing_physical_type)
    if imported_ps is None or existing_ps is None:
        return False
    return imported_ps[0] < existing_ps[0]


def decimal_scale_reduction(
    imported_physical_type: Any, existing_physical_type: Any
) -> bool:
    """Return True when the imported decimal scale is narrower than existing."""
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
