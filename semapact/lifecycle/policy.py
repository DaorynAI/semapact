from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)
from semapact.governance_codes import GovernanceReasonCode
from semapact.lifecycle.changes import (
    GovernanceChange,
    GovernanceChangeType,
    GovernanceEntityType,
    analyze_governance_changes,
)
from semapact.lifecycle.helpers import (
    decimal_precision_reduction,
    decimal_scale_reduction,
)
from semapact.lifecycle.identity import (
    PropertyIdentity,
    build_schema_index,
    build_property_index,
    validate_contract_identities,
)
from semapact.lifecycle.relationships import normalize_endpoint_value
from semapact.lifecycle.status import (
    is_active_contract,
    participates_in_breaking_checks,
    resolve_property_lifecycle,
    resolve_schema_lifecycle,
)

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class BreakingChange:
    """Detected breaking change in lifecycle evaluation."""

    code: GovernanceReasonCode
    path: str
    message: str


@dataclass(slots=True)
class PolicyEvaluation:
    """Lifecycle policy evaluation result."""

    valid: bool
    breaking_changes: list[BreakingChange] = field(default_factory=list)
    id_violation: bool = False
    version_violation: bool = False
    annotated_changes: tuple[GovernanceChange, ...] = ()


def evaluate_merge_policy(
    base_contract: OpenDataContractStandard,
    merged_contract: OpenDataContractStandard,
    *,
    changes: Sequence[GovernanceChange] | None = None,
) -> PolicyEvaluation:
    """Validate identities for all contracts and evaluate breaking changes for active contracts."""
    validate_contract_identities(base_contract)
    validate_contract_identities(merged_contract)

    canonical_changes = (
        analyze_governance_changes(base_contract, merged_contract)
        if changes is None
        else tuple(changes)
    )

    breaks: list[BreakingChange] = []
    id_violation = False
    version_violation = False
    annotated_changes: list[GovernanceChange] = []

    base_is_active = is_active_contract(base_contract)
    base_schema_index = build_schema_index(base_contract) if base_is_active else {}

    for change in canonical_changes:
        change_breaks: list[BreakingChange] = []
        change_reasons: list[GovernanceReasonCode] = list(change.reason_codes)

        # 1. Contract root violations
        if change.entity_type == GovernanceEntityType.CONTRACT:
            if change.field == "id":
                id_violation = True
                LOGGER.warning(
                    "Policy violation: Root ID changed in contract %s", base_contract.id
                )
                brk = BreakingChange(
                    code=GovernanceReasonCode.CONTRACT_ID_CHANGED,
                    path="id",
                    message="Contract ID mismatch. You changed the root ID of the contract, which is immutable. If you want to create a new contract, use 'semapact import --new' or change the ID back.",
                )
                change_breaks.append(brk)
                change_reasons.append(brk.code)
            elif change.field == "version":
                version_violation = True
                LOGGER.warning(
                    "Policy violation: Root version changed in contract %s", base_contract.id
                )
                brk = BreakingChange(
                    code=GovernanceReasonCode.CONTRACT_VERSION_MANUALLY_CHANGED,
                    path="version",
                    message="Contract version mismatch. Contract versions are release-managed and cannot be manually updated during normal import/merge. Please revert the version change and use 'semapact release prepare'.",
                )
                change_breaks.append(brk)
                change_reasons.append(brk.code)

        # 2. Active contract breaking change evaluation
        if base_is_active:
            if change.entity_type == GovernanceEntityType.SCHEMA:
                schema_id = change.identity[0]
                base_schema = base_schema_index.get(schema_id)
                if base_schema is not None:
                    schema_status = resolve_schema_lifecycle(base_schema, contract=base_contract)
                    if (
                        participates_in_breaking_checks(schema_status)
                        and change.change_type == GovernanceChangeType.REMOVE
                        and change.field is None
                    ):
                        brk = BreakingChange(
                            code=GovernanceReasonCode.SCHEMA_REMOVED,
                            path=change.path,
                            message="Schema removed from active contract",
                        )
                        change_breaks.append(brk)
                        change_reasons.append(brk.code)

            elif change.entity_type == GovernanceEntityType.RELATIONSHIP:
                schema_id = change.identity[0]
                base_schema = base_schema_index.get(schema_id)
                if base_schema is not None:
                    schema_status = resolve_schema_lifecycle(base_schema, contract=base_contract)
                    if participates_in_breaking_checks(schema_status) and change.change_type == GovernanceChangeType.REMOVE:
                        rel_hash = change.identity[1] if len(change.identity) > 1 else ""
                        brk = BreakingChange(
                            code=GovernanceReasonCode.RELATIONSHIP_REMOVED,
                            path=change.path,
                            message=f"Relationship '{rel_hash}' removed from active lifecycle scope. Downstream joins may fail.",
                        )
                        change_breaks.append(brk)
                        change_reasons.append(brk.code)

            elif change.entity_type == GovernanceEntityType.PROPERTY:
                schema_id = change.identity[0]
                prop_name = change.identity[1]
                base_schema = base_schema_index.get(schema_id)
                if base_schema is not None:
                    schema_status = resolve_schema_lifecycle(base_schema, contract=base_contract)
                    if participates_in_breaking_checks(schema_status):
                        base_props = build_property_index(schema_id, base_schema.properties or [])
                        base_prop = base_props.get((schema_id, prop_name))
                        if base_prop is not None:
                            prop_status = resolve_property_lifecycle(base_prop, parent_lifecycle=schema_status)
                            if participates_in_breaking_checks(prop_status):
                                if change.change_type == GovernanceChangeType.REMOVE and change.field is None:
                                    brk = BreakingChange(
                                        code=GovernanceReasonCode.PROPERTY_REMOVED,
                                        path=change.path,
                                        message="Property removed from active lifecycle scope",
                                    )
                                    change_breaks.append(brk)
                                    change_reasons.append(brk.code)
                                elif change.change_type == GovernanceChangeType.MODIFY:
                                    if change.field == "logicalType":
                                        b_log = change.before
                                        c_log = change.after
                                        if b_log is not None and c_log is not None and str(b_log) != str(c_log):
                                            brk = BreakingChange(
                                                code=GovernanceReasonCode.LOGICAL_TYPE_CHANGED,
                                                path=change.path,
                                                message=f"Logical type changed from {b_log!r} to {c_log!r}",
                                            )
                                            change_breaks.append(brk)
                                            change_reasons.append(brk.code)
                                    elif change.field == "physicalType":
                                        b_phys = change.before
                                        c_phys = change.after
                                        if _is_physical_type_narrowing(b_phys, c_phys):
                                            brk = BreakingChange(
                                                code=GovernanceReasonCode.PHYSICAL_TYPE_NARROWED,
                                                path=change.path,
                                                message=f"Physical type narrowed from {b_phys!r} to {c_phys!r}",
                                            )
                                            change_breaks.append(brk)
                                            change_reasons.append(brk.code)
                                        if decimal_precision_reduction(c_phys, b_phys):
                                            brk = BreakingChange(
                                                code=GovernanceReasonCode.DECIMAL_PRECISION_REDUCED,
                                                path=change.path,
                                                message=f"Decimal precision reduced from {b_phys!r} to {c_phys!r}",
                                            )
                                            change_breaks.append(brk)
                                            change_reasons.append(brk.code)
                                        if decimal_scale_reduction(c_phys, b_phys):
                                            brk = BreakingChange(
                                                code=GovernanceReasonCode.DECIMAL_SCALE_REDUCED,
                                                path=change.path,
                                                message=f"Decimal scale reduced from {b_phys!r} to {c_phys!r}",
                                            )
                                            change_breaks.append(brk)
                                            change_reasons.append(brk.code)
                                    elif change.field == "required":
                                        if change.before is False and change.after is True:
                                            brk = BreakingChange(
                                                code=GovernanceReasonCode.REQUIRED_TIGHTENED,
                                                path=change.path,
                                                message="Required flag tightened from False to True",
                                            )
                                            change_breaks.append(brk)
                                            change_reasons.append(brk.code)
                                    elif change.field == "enum":
                                        base_set = set(change.before) if isinstance(change.before, (list, tuple)) else set()
                                        cand_set = set(change.after) if isinstance(change.after, (list, tuple)) else set()
                                        if base_set and not base_set.issubset(cand_set):
                                            brk = BreakingChange(
                                                code=GovernanceReasonCode.ENUM_VALUES_REMOVED,
                                                path=change.path,
                                                message="Enum values reduced",
                                            )
                                            change_breaks.append(brk)
                                            change_reasons.append(brk.code)

        breaks.extend(change_breaks)
        sorted_reasons = tuple(sorted(set(change_reasons), key=lambda r: r.value))
        annotated_changes.append(
            change.model_copy(
                update={
                    "breaking": bool(change_breaks) or change.breaking,
                    "reason_codes": sorted_reasons,
                }
            )
        )

    if breaks:
        LOGGER.info(
            "Policy evaluation found %d breaking changes for contract %s",
            len(breaks),
            base_contract.id,
        )
    else:
        LOGGER.debug(
            "Policy evaluation passed with no breaking changes for contract %s",
            base_contract.id,
        )

    return PolicyEvaluation(
        valid=not breaks,
        breaking_changes=breaks,
        id_violation=id_violation,
        version_violation=version_violation,
        annotated_changes=tuple(annotated_changes),
    )


def _root_id_changed(
    base_contract: OpenDataContractStandard,
    merged_contract: OpenDataContractStandard,
) -> bool:
    base_id = str(base_contract.id or "").strip()
    merged_id = str(merged_contract.id or "").strip()
    if not base_id and not merged_id:
        return False
    return base_id != merged_id


def _root_version_changed(
    base_contract: OpenDataContractStandard,
    merged_contract: OpenDataContractStandard,
) -> bool:
    base_version = str(base_contract.version or "").strip()
    merged_version = str(merged_contract.version or "").strip()
    if not base_version and not merged_version:
        return False
    return base_version != merged_version



def _property_breaking_changes(
    base_prop: SchemaProperty,
    target_prop: SchemaProperty,
    path: str,
) -> list[BreakingChange]:
    breaks: list[BreakingChange] = []

    base_logical = base_prop.logicalType
    target_logical = target_prop.logicalType
    if (
        base_logical is not None
        and target_logical is not None
        and str(base_logical) != str(target_logical)
    ):
        breaks.append(
            BreakingChange(
                code=GovernanceReasonCode.LOGICAL_TYPE_CHANGED,
                path=f"{path}.logicalType",
                message=f"Logical type changed from {base_logical!r} to {target_logical!r}",
            )
        )

    base_physical = base_prop.physicalType
    target_physical = target_prop.physicalType

    if _is_physical_type_narrowing(base_physical, target_physical):
        breaks.append(
            BreakingChange(
                code=GovernanceReasonCode.PHYSICAL_TYPE_NARROWED,
                path=f"{path}.physicalType",
                message=f"Physical type narrowed from {base_physical!r} to {target_physical!r}",
            )
        )

    if decimal_precision_reduction(target_physical, base_physical):
        breaks.append(
            BreakingChange(
                code=GovernanceReasonCode.DECIMAL_PRECISION_REDUCED,
                path=f"{path}.physicalType",
                message=f"Decimal precision reduced from {base_physical!r} to {target_physical!r}",
            )
        )

    if decimal_scale_reduction(target_physical, base_physical):
        breaks.append(
            BreakingChange(
                code=GovernanceReasonCode.DECIMAL_SCALE_REDUCED,
                path=f"{path}.physicalType",
                message=f"Decimal scale reduced from {base_physical!r} to {target_physical!r}",
            )
        )

    base_required = base_prop.required
    target_required = target_prop.required
    if base_required is False and target_required is True:
        breaks.append(
            BreakingChange(
                code=GovernanceReasonCode.REQUIRED_TIGHTENED,
                path=f"{path}.required",
                message="Required flag tightened from False to True",
            )
        )

    if _is_enum_value_reduction(base_prop, target_prop):
        breaks.append(
            BreakingChange(
                code=GovernanceReasonCode.ENUM_VALUES_REMOVED,
                path=f"{path}.enum",
                message="Enum values reduced",
            )
        )

    return breaks


def _is_physical_type_narrowing(base_physical: Any, target_physical: Any) -> bool:
    if not isinstance(base_physical, str) or not isinstance(target_physical, str):
        return False

    base_type = base_physical.strip().lower()
    target_type = target_physical.strip().lower()
    if base_type == target_type:
        return False

    base_family = _physical_type_family(base_type)
    target_family = _physical_type_family(target_type)
    if base_family != target_family:
        return False

    base_width = _type_width(base_type)
    target_width = _type_width(target_type)
    if base_width is None or target_width is None:
        return False
    return target_width < base_width


def _physical_type_family(physical_type: str) -> str:
    if physical_type.startswith(("varchar", "char", "string", "text")):
        return "string"
    if physical_type.startswith(("varbinary", "binary")):
        return "binary"
    if physical_type.startswith(("tinyint", "smallint", "int", "integer", "bigint")):
        return "integer"
    return physical_type.split("(", 1)[0]


def _type_width(physical_type: str) -> int | None:
    integer_widths = {
        "tinyint": 8,
        "smallint": 16,
        "int": 32,
        "integer": 32,
        "bigint": 64,
    }
    if physical_type in integer_widths:
        return integer_widths[physical_type]

    string_match = re.match(r"^(?:var)?char\((\d+)\)$", physical_type)
    if string_match:
        return int(string_match.group(1))

    binary_match = re.match(r"^(?:var)?binary\((\d+)\)$", physical_type)
    if binary_match:
        return int(binary_match.group(1))

    return None


def _is_enum_value_reduction(
    base_prop: SchemaProperty,
    target_prop: SchemaProperty,
) -> bool:
    base_values = _enum_values(base_prop)
    target_values = _enum_values(target_prop)
    if not base_values or not target_values:
        return False
    return not base_values.issubset(target_values)


def _enum_values(prop: SchemaProperty) -> set[str]:
    for key in ("enum", "enumValues"):
        values = getattr(prop, key, None)
        if not isinstance(values, list):
            continue
        return {str(item) for item in values}
    return set()


def _extract_relationship_hashes(
    schema: SchemaObject, schema_properties: dict[PropertyIdentity, SchemaProperty]
) -> set[str]:
    hashes = set()

    # 1. Schema-level relationships
    rels = getattr(schema, "relationships", None)
    if rels:
        for rel in rels:
            rel_type = getattr(rel, "type", "") or "foreignKey"
            from_val = getattr(rel, "from_", None) or getattr(rel, "from", None) or ""
            to_val = getattr(rel, "to", None) or ""

            from_str = normalize_endpoint_value(from_val)
            to_str = normalize_endpoint_value(to_val)

            hashes.add(f"{rel_type}:{from_str}->{to_str}")

    # 2. Property-level relationships: from_str derived from PropertyIdentity
    for prop_key, prop in schema_properties.items():
        prop_rels = getattr(prop, "relationships", None)
        if prop_rels:
            for rel in prop_rels:
                rel_type = getattr(rel, "type", "") or "foreignKey"
                to_val = getattr(rel, "to", None) or ""
                from_str = f"{prop_key[0]}.{prop_key[1]}"
                to_str = normalize_endpoint_value(to_val)
                hashes.add(f"{rel_type}:{from_str}->{to_str}")

    return hashes
