"""Regression tests for explicit, deterministic ChangeContext behavior."""

from __future__ import annotations

from datetime import date

import pytest
from open_data_contract_standard.model import (
    CustomProperty,
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)
from pydantic import ValidationError as PydanticValidationError

from semapact.governance import ChangeContext, evaluate_governance_decision
from semapact.lifecycle.merge_engine import ContractMergeEngine


def _cp(key: str, value: str) -> CustomProperty:
    return CustomProperty(property=key, value=value)


def _active_property(name: str, physical_type: str = "STRING") -> SchemaProperty:
    return SchemaProperty(
        name=name,
        physicalType=physical_type,
        logicalType="string",
        customProperties=[_cp("lifecycleStatus", "active")],
    )


def _contract(*, include_legacy_property: bool = True, include_legacy_schema: bool = False) -> OpenDataContractStandard:
    properties = [_active_property("id")]
    if include_legacy_property:
        properties.append(_active_property("legacy_col"))

    schemas = [
        SchemaObject(
            name="orders",
            customProperties=[_cp("lifecycleStatus", "active")],
            properties=properties,
        )
    ]
    if include_legacy_schema:
        schemas.append(
            SchemaObject(
                name="legacy_orders",
                customProperties=[_cp("lifecycleStatus", "active")],
                properties=[_active_property("id")],
            )
        )

    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="orders",
        name="orders",
        version="1.0.0",
        status="active",
        schema=schemas,
    )


def _custom_property_value(entity: object, key: str) -> str | None:
    for item in getattr(entity, "customProperties", None) or []:
        if str(item.property or "").strip().lower() == key.lower():
            return str(item.value)
    return None


def test_change_context_requires_effective_date() -> None:
    with pytest.raises(PydanticValidationError):
        ChangeContext()  # type: ignore[call-arg]


def test_change_context_is_immutable_and_serializes_effective_date() -> None:
    context = ChangeContext(effective_date=date(2026, 8, 13))

    assert context.model_dump(mode="json") == {"effective_date": "2026-08-13"}
    with pytest.raises(PydanticValidationError):
        context.effective_date = date(2026, 8, 14)  # type: ignore[misc]


def test_same_inputs_and_context_produce_identical_decision() -> None:
    base = _contract()
    candidate = _contract(include_legacy_property=False)
    context = ChangeContext(effective_date=date(2026, 8, 13))

    first = evaluate_governance_decision(base, candidate, context=context)
    second = evaluate_governance_decision(base, candidate, context=context)

    assert first == second
    assert first.decision_id == second.decision_id
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.context == context


def test_governance_evaluation_rejects_missing_upstream_context() -> None:
    base = _contract()
    candidate = _contract(include_legacy_property=False)

    with pytest.raises(TypeError):
        evaluate_governance_decision(base, candidate)  # type: ignore[call-arg]


def test_effective_date_is_part_of_decision_identity_when_explicit() -> None:
    base = _contract()
    candidate = _contract(include_legacy_property=False)

    first = evaluate_governance_decision(
        base,
        candidate,
        context=ChangeContext(effective_date=date(2026, 8, 13)),
    )
    second = evaluate_governance_decision(
        base,
        candidate,
        context=ChangeContext(effective_date=date(2026, 8, 14)),
    )

    assert first.decision == second.decision
    assert first.decision_id != second.decision_id


def test_auto_deprecation_uses_explicit_effective_date() -> None:
    governed = _contract(include_legacy_schema=True)
    source = _contract(include_legacy_property=False)
    context = ChangeContext(effective_date=date(2026, 8, 13))

    merged = ContractMergeEngine().merge(source, governed, context=context).contract
    orders = next(schema for schema in merged.schema_ or [] if schema.name == "orders")
    legacy_property = next(
        prop for prop in orders.properties or [] if prop.name == "legacy_col"
    )
    legacy_schema = next(
        schema for schema in merged.schema_ or [] if schema.name == "legacy_orders"
    )

    assert _custom_property_value(legacy_property, "deprecationDate") == "2026-08-13"
    assert _custom_property_value(legacy_schema, "deprecationDate") == "2026-08-13"


def test_existing_deprecation_date_is_not_overwritten() -> None:
    governed = _contract()
    orders = governed.schema_[0]
    legacy_property = next(
        prop for prop in orders.properties or [] if prop.name == "legacy_col"
    )
    legacy_property.customProperties = [
        _cp("lifecycleStatus", "active"),
        _cp("deprecationDate", "2026-07-01"),
    ]
    source = _contract(include_legacy_property=False)

    merged = ContractMergeEngine().merge(
        source,
        governed,
        context=ChangeContext(effective_date=date(2026, 8, 13)),
    ).contract
    merged_orders = next(schema for schema in merged.schema_ or [] if schema.name == "orders")
    merged_legacy = next(
        prop for prop in merged_orders.properties or [] if prop.name == "legacy_col"
    )

    assert _custom_property_value(merged_legacy, "deprecationDate") == "2026-07-01"


def test_merge_rejects_missing_upstream_context() -> None:
    governed = _contract()
    source = _contract(include_legacy_property=False)

    with pytest.raises(TypeError):
        ContractMergeEngine().merge(source, governed)  # type: ignore[call-arg]
