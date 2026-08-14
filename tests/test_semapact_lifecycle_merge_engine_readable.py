from __future__ import annotations

from datetime import date

import pytest
from open_data_contract_standard.model import (
    CustomProperty,
    DataQuality,
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

import semapact.lifecycle.merge_engine as merge_engine
from semapact.governance import ChangeContext
from semapact.lifecycle.merge_engine import ContractMergeEngine


TEST_CONTEXT = ChangeContext(effective_date=date(2026, 1, 1))


def _cp(key: str, value: str) -> CustomProperty:
    return CustomProperty(property=key, value=value)


def _build_base_contract() -> OpenDataContractStandard:
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
                physicalName="orders",
                customProperties=[_cp("lifecycleStatus", "active")],
                properties=[
                    SchemaProperty(
                        name="id",
                        physicalName="id",
                        logicalType="integer",
                        physicalType="int",
                        required=True,
                        customProperties=[_cp("lifecycleStatus", "active")],
                        quality=[
                            DataQuality(
                                name="id_not_null", metric="nullValues", mustBe=0
                            )
                        ],
                    ),
                    SchemaProperty(
                        name="amount",
                        physicalName="amount",
                        logicalType="number",
                        physicalType="decimal(10,2)",
                        customProperties=[_cp("lifecycleStatus", "active")],
                    ),
                ],
                quality=[
                    DataQuality(
                        name="row_count", metric="rowCount", mustBeGreaterThan=0
                    )
                ],
            )
        ],
    )


def _build_business_contract() -> OpenDataContractStandard:
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
                physicalName="orders",
                customProperties=[_cp("lifecycleStatus", "active")],
                properties=[
                    SchemaProperty(
                        name="id",
                        physicalName="id",
                        logicalType="string",
                        physicalType="varchar(18)",
                        required=False,
                        customProperties=[_cp("lifecycleStatus", "active")],
                        quality=[
                            DataQuality(
                                name="id_duplicate_count",
                                metric="duplicateValues",
                                mustBe=0,
                            )
                        ],
                    ),
                    SchemaProperty(
                        name="amount",
                        physicalName="amount",
                        logicalType="number",
                        physicalType="decimal(12,4)",
                        customProperties=[_cp("lifecycleStatus", "active")],
                    ),
                ],
                quality=[
                    DataQuality(
                        name="row_count_upper_bound",
                        metric="rowCount",
                        mustBeLessThan=1000,
                    )
                ],
            )
        ],
    )


def test_merge_engine_detects_type_required_and_decimal_conflicts():
    engine = ContractMergeEngine()

    conflicts = engine.detect_conflicts(
        _build_base_contract(), _build_business_contract()
    )

    rules = {item.rule for item in conflicts}
    assert "logical_type_mismatch" in rules
    assert "physical_type_change" in rules
    assert "required_tightening" in rules
    assert "decimal_precision_reduction" in rules
    assert "decimal_scale_reduction" in rules


def test_merge_engine_can_fail_fast_when_conflicts_exist():
    engine = ContractMergeEngine()

    with pytest.raises(Exception, match="Merge conflicts detected"):
        engine.merge(
            _build_base_contract(),
            _build_business_contract(),
            context=TEST_CONTEXT,
            fail_on_conflict=True,
        )


def test_merge_engine_combines_quality_rules_without_duplicates():
    engine = ContractMergeEngine()

    result = engine.merge(
        _build_base_contract(), _build_business_contract(), context=TEST_CONTEXT
    )

    merged_schema = result.contract.schema_[0]  # type: ignore[index]
    schema_quality = merged_schema.quality
    id_property = next(
        prop for prop in (merged_schema.properties or []) if prop.name == "id"
    )
    id_quality = id_property.quality

    assert schema_quality is not None and len(schema_quality) == 2
    assert id_quality is not None and len(id_quality) == 2


def test_merge_engine_helpers_cover_edge_cases_for_internal_functions():
    assert merge_engine._value_conflict("a", "b") is True  # noqa: SLF001
    assert merge_engine._value_conflict(None, "b") is False  # noqa: SLF001
    assert merge_engine._decimal_precision_scale("decimal(9,2)") == (9, 2)  # noqa: SLF001
    assert merge_engine._decimal_precision_scale("int") is None  # noqa: SLF001
    assert (
        merge_engine._decimal_precision_reduction("decimal(8,2)", "decimal(10,2)")
        is True
    )  # noqa: SLF001
    assert (
        merge_engine._decimal_scale_reduction("decimal(10,1)", "decimal(10,2)") is True
    )  # noqa: SLF001


def test_merge_engine_skips_breaking_checks_for_draft_property():
    base = OpenDataContractStandard(
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
                properties=[
                    SchemaProperty(
                        name="id",
                        logicalType="integer",
                        physicalType="int",
                        customProperties=[_cp("lifecycleStatus", "active")],
                    )
                ],
            )
        ],
    )
    business = OpenDataContractStandard(
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
                properties=[
                    SchemaProperty(
                        name="id",
                        logicalType="string",
                        physicalType="varchar(32)",
                        customProperties=[_cp("lifecycleStatus", "draft")],
                    )
                ],
            )
        ],
    )

    conflicts = ContractMergeEngine().detect_conflicts(base, business)
    assert conflicts == []


def test_merge_engine_detects_temporal_type_changes_on_fixture(
    sample_temporal_types_contract_model,
):
    base = sample_temporal_types_contract_model.model_copy(deep=True)
    target = sample_temporal_types_contract_model.model_copy(deep=True)
    assert base.schema_ is not None
    assert target.schema_ is not None
    assert base.schema_[0].properties is not None
    assert target.schema_[0].properties is not None

    target_event_ts = next(
        prop for prop in target.schema_[0].properties if prop.name == "event_ts"
    )
    target_event_ts.logicalType = "date"
    target_event_ts.physicalType = "DATE"

    conflicts = ContractMergeEngine().detect_conflicts(base, target)

    conflict_rules = {item.rule for item in conflicts}
    assert "logical_type_mismatch" in conflict_rules
    assert "physical_type_change" in conflict_rules


def test_merge_engine_allows_decimal_widening_on_numeric_fixture(
    sample_numeric_precision_contract_model,
):
    base = sample_numeric_precision_contract_model.model_copy(deep=True)
    target = sample_numeric_precision_contract_model.model_copy(deep=True)
    assert base.schema_ is not None
    assert target.schema_ is not None
    assert base.schema_[0].properties is not None
    assert target.schema_[0].properties is not None

    base_fx_rate = next(
        prop for prop in base.schema_[0].properties if prop.name == "fx_rate"
    )
    target_fx_rate = next(
        prop for prop in target.schema_[0].properties if prop.name == "fx_rate"
    )
    base_fx_rate.physicalType = "DECIMAL(20,8)"
    target_fx_rate.physicalType = "DECIMAL(18,6)"

    conflicts = ContractMergeEngine().detect_conflicts(base, target)
    fx_rate_conflicts = [item for item in conflicts if "fx_rate" in item.path]

    assert fx_rate_conflicts == []
