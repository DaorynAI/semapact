from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from open_data_contract_standard.model import OpenDataContractStandard

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
    build_property_index,
    build_schema_index,
    validate_contract_identities,
)
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
    """Lifecycle policy evidence for governance evaluation.

    ``valid`` means no policy-breaking findings were detected. It is not an
    operation-authorization result; authorization is determined by the
    GovernanceDecision and the operation-specific governance gate.
    """

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
    """Validate identities and annotate canonical changes with policy findings."""
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

        # Contract root violations are evaluated regardless of lifecycle state.
        if change.entity_type == GovernanceEntityType.CONTRACT:
            if change.field == "id":
                id_violation = True
                LOGGER.warning(
                    "Policy violation: Root ID changed in contract %s", base_contract.id
                )
                breaking = BreakingChange(
                    code=GovernanceReasonCode.CONTRACT_ID_CHANGED,
                    path="id",
                    message=(
                        "Contract ID mismatch. You changed the root ID of the contract, "
                        "which is immutable. If you want to create a new contract, use "
                        "'semapact import --new' or change the ID back."
                    ),
                )
                change_breaks.append(breaking)
                change_reasons.append(breaking.code)
            elif change.field == "version":
                version_violation = True
                LOGGER.warning(
                    "Policy violation: Root version changed in contract %s",
                    base_contract.id,
                )
                breaking = BreakingChange(
                    code=GovernanceReasonCode.CONTRACT_VERSION_MANUALLY_CHANGED,
                    path="version",
                    message=(
                        "Contract version mismatch. Contract versions are release-managed "
                        "and cannot be manually updated during normal import/merge. Please "
                        "revert the version change and use 'semapact release prepare'."
                    ),
                )
                change_breaks.append(breaking)
                change_reasons.append(breaking.code)

        # Breaking-change policy applies only to active lifecycle scope.
        if base_is_active:
            if change.entity_type == GovernanceEntityType.SCHEMA:
                schema_id = change.identity[0]
                base_schema = base_schema_index.get(schema_id)
                if base_schema is not None:
                    schema_status = resolve_schema_lifecycle(
                        base_schema,
                        contract=base_contract,
                    )
                    if (
                        participates_in_breaking_checks(schema_status)
                        and change.change_type == GovernanceChangeType.REMOVE
                        and change.field is None
                    ):
                        breaking = BreakingChange(
                            code=GovernanceReasonCode.SCHEMA_REMOVED,
                            path=change.path,
                            message="Schema removed from active contract",
                        )
                        change_breaks.append(breaking)
                        change_reasons.append(breaking.code)

            elif change.entity_type == GovernanceEntityType.RELATIONSHIP:
                schema_id = change.identity[0]
                base_schema = base_schema_index.get(schema_id)
                if base_schema is not None:
                    schema_status = resolve_schema_lifecycle(
                        base_schema,
                        contract=base_contract,
                    )
                    if (
                        participates_in_breaking_checks(schema_status)
                        and change.change_type == GovernanceChangeType.REMOVE
                    ):
                        relationship_identity = change.identity[-1]
                        breaking = BreakingChange(
                            code=GovernanceReasonCode.RELATIONSHIP_REMOVED,
                            path=change.path,
                            message=(
                                f"Relationship '{relationship_identity}' removed from active "
                                "lifecycle scope. Downstream joins may fail."
                            ),
                        )
                        change_breaks.append(breaking)
                        change_reasons.append(breaking.code)

            elif change.entity_type == GovernanceEntityType.PROPERTY:
                schema_id = change.identity[0]
                property_name = change.identity[1]
                base_schema = base_schema_index.get(schema_id)
                if base_schema is not None:
                    schema_status = resolve_schema_lifecycle(
                        base_schema,
                        contract=base_contract,
                    )
                    if participates_in_breaking_checks(schema_status):
                        base_properties = build_property_index(
                            schema_id,
                            base_schema.properties or [],
                        )
                        base_property = base_properties.get((schema_id, property_name))
                        if base_property is not None:
                            property_status = resolve_property_lifecycle(
                                base_property,
                                parent_lifecycle=schema_status,
                            )
                            if participates_in_breaking_checks(property_status):
                                if (
                                    change.change_type == GovernanceChangeType.REMOVE
                                    and change.field is None
                                ):
                                    breaking = BreakingChange(
                                        code=GovernanceReasonCode.PROPERTY_REMOVED,
                                        path=change.path,
                                        message="Property removed from active lifecycle scope",
                                    )
                                    change_breaks.append(breaking)
                                    change_reasons.append(breaking.code)
                                elif change.change_type == GovernanceChangeType.MODIFY:
                                    if change.field == "logicalType":
                                        before = change.before
                                        after = change.after
                                        if (
                                            before is not None
                                            and after is not None
                                            and str(before) != str(after)
                                        ):
                                            breaking = BreakingChange(
                                                code=GovernanceReasonCode.LOGICAL_TYPE_CHANGED,
                                                path=change.path,
                                                message=(
                                                    f"Logical type changed from {before!r} "
                                                    f"to {after!r}"
                                                ),
                                            )
                                            change_breaks.append(breaking)
                                            change_reasons.append(breaking.code)
                                    elif change.field == "physicalType":
                                        before = change.before
                                        after = change.after
                                        if _is_physical_type_narrowing(before, after):
                                            breaking = BreakingChange(
                                                code=GovernanceReasonCode.PHYSICAL_TYPE_NARROWED,
                                                path=change.path,
                                                message=(
                                                    f"Physical type narrowed from {before!r} "
                                                    f"to {after!r}"
                                                ),
                                            )
                                            change_breaks.append(breaking)
                                            change_reasons.append(breaking.code)
                                        if decimal_precision_reduction(after, before):
                                            breaking = BreakingChange(
                                                code=GovernanceReasonCode.DECIMAL_PRECISION_REDUCED,
                                                path=change.path,
                                                message=(
                                                    f"Decimal precision reduced from {before!r} "
                                                    f"to {after!r}"
                                                ),
                                            )
                                            change_breaks.append(breaking)
                                            change_reasons.append(breaking.code)
                                        if decimal_scale_reduction(after, before):
                                            breaking = BreakingChange(
                                                code=GovernanceReasonCode.DECIMAL_SCALE_REDUCED,
                                                path=change.path,
                                                message=(
                                                    f"Decimal scale reduced from {before!r} "
                                                    f"to {after!r}"
                                                ),
                                            )
                                            change_breaks.append(breaking)
                                            change_reasons.append(breaking.code)
                                    elif change.field == "required":
                                        if change.before is False and change.after is True:
                                            breaking = BreakingChange(
                                                code=GovernanceReasonCode.REQUIRED_TIGHTENED,
                                                path=change.path,
                                                message=(
                                                    "Required flag tightened from False to True"
                                                ),
                                            )
                                            change_breaks.append(breaking)
                                            change_reasons.append(breaking.code)
                                    elif change.field == "enum":
                                        base_values = (
                                            set(change.before)
                                            if isinstance(change.before, (list, tuple))
                                            else set()
                                        )
                                        candidate_values = (
                                            set(change.after)
                                            if isinstance(change.after, (list, tuple))
                                            else set()
                                        )
                                        if base_values and not base_values.issubset(
                                            candidate_values
                                        ):
                                            breaking = BreakingChange(
                                                code=GovernanceReasonCode.ENUM_VALUES_REMOVED,
                                                path=change.path,
                                                message="Enum values reduced",
                                            )
                                            change_breaks.append(breaking)
                                            change_reasons.append(breaking.code)

        breaks.extend(change_breaks)
        sorted_reasons = tuple(
            sorted(set(change_reasons), key=lambda reason: reason.value)
        )
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


def _is_physical_type_narrowing(
    base_physical: Any,
    target_physical: Any,
) -> bool:
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
