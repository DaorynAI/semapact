import pytest
from open_data_contract_standard.model import SchemaObject, SchemaProperty
from semapact.core.release import classify_contract_change
from semapact.exceptions import ValidationError
from semapact.lifecycle.merge_engine import ContractMergeEngine
from semapact.lifecycle.policy import evaluate_merge_policy


def test_cross_layer_entity_consistency(sample_odcs_model):
    base = sample_odcs_model.model_copy(deep=True)
    base.status = "active"
    assert base.schema_ is not None
    assert base.schema_[0].properties is not None
    base.schema_[0].name = "  Orders  "
    base.schema_[0].physicalName = "orders_v1"
    base.schema_[0].properties[0].name = "  Id  "

    candidate = sample_odcs_model.model_copy(deep=True)
    candidate.status = "active"
    assert candidate.schema_ is not None
    assert candidate.schema_[0].properties is not None
    candidate.schema_[0].name = "orders"
    candidate.schema_[0].physicalName = "orders_v2"
    candidate.schema_[0].properties[0].name = "id"

    # 1. Policy: case/whitespace difference must NOT trigger breaking changes
    evaluation = evaluate_merge_policy(base, candidate)
    assert evaluation.valid is True
    assert evaluation.breaking_changes == []

    # 2. Merge Engine: schemas must be merged (not duplicated) by canonical key
    engine = ContractMergeEngine()
    merged = engine.merge(base, candidate)
    assert merged.contract.schema_ is not None
    assert len(merged.contract.schema_) == len(base.schema_)
    assert len(merged.contract.schema_[0].properties) == len(base.schema_[0].properties)

    # 3. Release: physicalName change alone is a non-breaking minor bump;
    #    must NOT be classified as an addition.
    bump = classify_contract_change(base, candidate)
    assert bump.required_bump == "minor"
    assert not any(
        "Schema or property additions" in r for r in bump.reasons
    )


def test_policy_case_insensitivity_matching(sample_odcs_model):
    base = sample_odcs_model.model_copy(deep=True)
    base.status = "active"
    assert base.schema_ is not None
    base.schema_[0].name = "ORDERS"
    assert base.schema_[0].properties is not None
    base.schema_[0].properties[0].name = "ID"

    merged = sample_odcs_model.model_copy(deep=True)
    merged.status = "active"
    assert merged.schema_ is not None
    merged.schema_[0].name = "orders"
    assert merged.schema_[0].properties is not None
    merged.schema_[0].properties[0].name = "id"

    evaluation = evaluate_merge_policy(base, merged)
    assert evaluation.valid is True
    assert evaluation.breaking_changes == []


def test_policy_physical_name_does_not_override_logical_name(sample_odcs_model):
    base = sample_odcs_model.model_copy(deep=True)
    base.status = "active"
    assert base.schema_ is not None
    base.schema_[0].name = "orders"
    base.schema_[0].physicalName = "orders_physical"

    merged = sample_odcs_model.model_copy(deep=True)
    merged.status = "active"
    assert merged.schema_ is not None
    merged.schema_[0].name = "orders"
    merged.schema_[0].physicalName = "orders_physical_new"

    evaluation = evaluate_merge_policy(base, merged)
    assert evaluation.valid is True
    assert evaluation.breaking_changes == []


def test_policy_missing_or_invalid_names_raise_validation_error(sample_odcs_model):
    base = sample_odcs_model.model_copy(deep=True)
    base.status = "active"

    # Missing schema name
    invalid_base = base.model_copy(deep=True)
    assert invalid_base.schema_ is not None
    invalid_base.schema_[0].name = None
    with pytest.raises(ValidationError) as exc_info:
        evaluate_merge_policy(invalid_base, base)
    assert "Schema name is missing" in str(exc_info.value)

    # Empty schema name
    invalid_base.schema_[0].name = "   "
    with pytest.raises(ValidationError) as exc_info:
        evaluate_merge_policy(invalid_base, base)
    assert "Schema name cannot be empty or whitespace-only" in str(exc_info.value)

    # Missing property name
    invalid_base2 = base.model_copy(deep=True)
    assert invalid_base2.schema_ is not None
    assert invalid_base2.schema_[0].properties is not None
    invalid_base2.schema_[0].properties[0].name = None
    with pytest.raises(ValidationError) as exc_info:
        evaluate_merge_policy(invalid_base2, base)
    assert "Property name is missing" in str(exc_info.value)


def test_duplicate_canonical_identity_validation(sample_odcs_model):
    sample_odcs_model.status = "active"

    # Duplicate schema name in candidate
    invalid_contract = sample_odcs_model.model_copy(deep=True)
    invalid_contract.status = "active"
    assert invalid_contract.schema_ is not None
    duplicate_schema = SchemaObject(name="TBL", properties=[])
    invalid_contract.schema_.append(duplicate_schema)

    with pytest.raises(ValidationError) as exc_info:
        evaluate_merge_policy(sample_odcs_model, invalid_contract)
    assert "Duplicate canonical schema identity found: 'tbl'" in str(exc_info.value)

    engine = ContractMergeEngine()
    with pytest.raises(ValidationError) as exc_info:
        engine.merge(sample_odcs_model, invalid_contract)
    assert "Duplicate canonical schema identity found: 'tbl'" in str(exc_info.value)

    with pytest.raises(ValidationError) as exc_info:
        classify_contract_change(sample_odcs_model, invalid_contract)
    assert "Duplicate canonical schema identity found: 'tbl'" in str(exc_info.value)

    # Duplicate property name in candidate
    invalid_contract2 = sample_odcs_model.model_copy(deep=True)
    invalid_contract2.status = "active"
    assert invalid_contract2.schema_ is not None
    assert invalid_contract2.schema_[0].properties is not None
    duplicate_prop = SchemaProperty(name="RCVR_ID", type="string")
    invalid_contract2.schema_[0].properties.append(duplicate_prop)

    with pytest.raises(ValidationError) as exc_info:
        evaluate_merge_policy(sample_odcs_model, invalid_contract2)
    assert "Duplicate canonical property identity found: 'rcvr_id'" in str(exc_info.value)

    with pytest.raises(ValidationError) as exc_info:
        engine.merge(sample_odcs_model, invalid_contract2)
    assert "Duplicate canonical property identity found: 'rcvr_id'" in str(exc_info.value)

    with pytest.raises(ValidationError) as exc_info:
        classify_contract_change(sample_odcs_model, invalid_contract2)
    assert "Duplicate canonical property identity found: 'rcvr_id'" in str(exc_info.value)


def test_duplicate_canonical_schema_in_base_raises_validation_error(sample_odcs_model):
    base = sample_odcs_model.model_copy(deep=True)
    base.status = "active"
    assert base.schema_ is not None
    base.schema_.append(SchemaObject(name="TBL", properties=[]))

    candidate = sample_odcs_model.model_copy(deep=True)
    candidate.status = "active"

    with pytest.raises(ValidationError) as exc_info:
        evaluate_merge_policy(base, candidate)
    assert "Duplicate canonical schema identity found: 'tbl'" in str(exc_info.value)


def test_missing_property_name_in_new_schema(sample_odcs_model):
    sample_odcs_model.status = "active"
    candidate = sample_odcs_model.model_copy(deep=True)
    candidate.status = "active"
    assert candidate.schema_ is not None
    new_schema = SchemaObject(name="new_schema", properties=[SchemaProperty(name=None, type="string")])
    candidate.schema_.append(new_schema)

    with pytest.raises(ValidationError) as exc_info:
        evaluate_merge_policy(sample_odcs_model, candidate)
    assert "Property name is missing" in str(exc_info.value)
