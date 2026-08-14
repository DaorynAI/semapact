"""Tests for the application governance service boundary."""

from __future__ import annotations

from datetime import date

import pytest
from open_data_contract_standard.model import (
    CustomProperty,
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.services import GovernanceService


def _cp(key: str, value: str) -> CustomProperty:
    return CustomProperty(property=key, value=value)


def _contract(*, include_legacy: bool = True) -> OpenDataContractStandard:
    properties = [
        SchemaProperty(
            name="id",
            logicalType="string",
            physicalType="STRING",
            customProperties=[_cp("lifecycleStatus", "active")],
        )
    ]
    if include_legacy:
        properties.append(
            SchemaProperty(
                name="legacy_col",
                logicalType="string",
                physicalType="STRING",
                customProperties=[_cp("lifecycleStatus", "active")],
            )
        )

    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="orders",
        name="orders",
        version="1.0.0",
        status="active",
        schema=[
            SchemaObject(
                name="orders",
                customProperties=[_cp("lifecycleStatus", "active")],
                properties=properties,
            )
        ],
    )


def _custom_property_value(entity: object, key: str) -> str | None:
    for item in getattr(entity, "customProperties", None) or []:
        if str(item.property or "").strip().lower() == key.lower():
            return str(item.value)
    return None


def test_governance_service_constructs_context_from_request_value() -> None:
    decision = GovernanceService().evaluate(
        _contract(),
        _contract(),
        effective_date="2026-08-13",
    )

    assert decision.context.effective_date == date(2026, 8, 13)


def test_governance_service_reuses_context_for_merge_and_evaluation() -> None:
    governed = _contract()
    source = _contract(include_legacy=False)

    analysis = GovernanceService().merge_and_evaluate(
        source,
        governed,
        effective_date="2026-08-13",
    )

    merged_property = next(
        prop
        for prop in analysis.merge_result.contract.schema_[0].properties or []
        if prop.name == "legacy_col"
    )

    assert analysis.decision.context == analysis.context
    assert analysis.context.effective_date == date(2026, 8, 13)
    assert _custom_property_value(merged_property, "deprecationDate") == "2026-08-13"


def test_governance_service_rejects_invalid_effective_date() -> None:
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        GovernanceService.create_context("13-08-2026")
