from __future__ import annotations

import re
from typing import Any

from open_data_contract_standard.model import OpenDataContractStandard

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

__all__ = [
    "LIFECYCLE_STATUS_PROPERTY",
    "LifecycleStatus",
    "decimal_precision_reduction",
    "decimal_scale_reduction",
    "is_active_contract",
    "is_explicitly_deprecated",
    "is_retired_contract",
    "lifecycle_from_custom_properties",
    "normalize_status",
    "participates_in_breaking_checks",
    "resolve_contract_lifecycle",
    "resolve_declared_entity_lifecycle",
    "resolve_property_lifecycle",
    "resolve_schema_lifecycle",
    "schema_items",
]


def schema_items(contract: OpenDataContractStandard) -> list[Any]:

    """Return schema entries for the ODCS contract."""
    return list(contract.schema_ or [])


# Keep private alias for backwards compatibility
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
