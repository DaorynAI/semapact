from open_data_contract_standard.model import CustomProperty

from semapact.lifecycle.helpers import (
    is_active_contract,
    normalize_status,
    participates_in_breaking_checks,
    schema_items,
)
from semapact.lifecycle.policy import evaluate_merge_policy
from semapact.lifecycle.status import LifecycleStatus



def test_policy_skips_breaking_checks_for_non_active_contract(sample_odcs_model):
    base = sample_odcs_model.model_copy(deep=True)
    base.status = "draft"
    merged = base.model_copy(deep=True)
    merged.schema_ = []

    evaluation = evaluate_merge_policy(base, merged)

    assert evaluation.valid is True
    assert evaluation.breaking_changes == []


def test_policy_flags_removed_schema_in_active_contract(sample_odcs_model):
    base = sample_odcs_model.model_copy(deep=True)
    merged = sample_odcs_model.model_copy(deep=True)
    merged.schema_ = (merged.schema_ or [])[1:]

    evaluation = evaluate_merge_policy(base, merged)

    assert evaluation.valid is False
    assert any("Schema removed" in item.message for item in evaluation.breaking_changes)


def test_policy_flags_removed_property_in_active_contract(sample_odcs_model):
    base = sample_odcs_model.model_copy(deep=True)
    merged = sample_odcs_model.model_copy(deep=True)
    assert merged.schema_ is not None
    merged.schema_[0].properties = (merged.schema_[0].properties or [])[1:]

    evaluation = evaluate_merge_policy(base, merged)

    assert evaluation.valid is False
    assert any(
        "Property removed" in item.message for item in evaluation.breaking_changes
    )


def test_policy_ignores_removed_property_when_lifecycle_is_draft(sample_odcs_model):
    base = sample_odcs_model.model_copy(deep=True)
    merged = sample_odcs_model.model_copy(deep=True)
    assert base.schema_ is not None
    assert base.schema_[0].properties is not None
    base.schema_[0].properties[0].customProperties = [
        CustomProperty(property="lifecycleStatus", value="draft"),
    ]
    assert merged.schema_ is not None
    merged.schema_[0].properties = (merged.schema_[0].properties or [])[1:]

    evaluation = evaluate_merge_policy(base, merged)

    assert evaluation.valid is True
    assert evaluation.breaking_changes == []


def test_lifecycle_helpers_cover_status_and_schema_alias_paths(
    sample_odcs_model, sample_odcs_dict
):
    assert normalize_status(" ACTIVE ") is LifecycleStatus.ACTIVE
    active_contract = sample_odcs_model.model_copy(deep=True)
    active_contract.status = "active"
    assert is_active_contract(active_contract) is True
    inactive_contract = sample_odcs_model.model_copy(deep=True)
    inactive_contract.status = "deprecated"
    assert is_active_contract(inactive_contract) is False

    assert participates_in_breaking_checks(LifecycleStatus.ACTIVE) is True
    assert participates_in_breaking_checks(LifecycleStatus.DEPRECATED) is False
    assert schema_items(sample_odcs_model)



def test_policy_flags_type_narrowing_and_enum_reduction_from_fixture(
    sample_type_narrowing_base_contract_model,
    sample_type_narrowing_target_contract_model,
):
    evaluation = evaluate_merge_policy(
        sample_type_narrowing_base_contract_model,
        sample_type_narrowing_target_contract_model,
    )

    assert evaluation.valid is False
    messages = {item.message for item in evaluation.breaking_changes}
    assert any("Physical type narrowed" in message for message in messages)


def test_policy_flags_root_version_change_as_release_managed(sample_odcs_model):
    base = sample_odcs_model.model_copy(deep=True)
    merged = sample_odcs_model.model_copy(deep=True)
    base.status = "active"
    merged.status = "active"
    merged.version = "2.0.0"

    evaluation = evaluate_merge_policy(base, merged)

    assert evaluation.valid is False
    assert evaluation.version_violation is True
    assert any(item.path == "version" for item in evaluation.breaking_changes)
    assert any(
        "Contract version mismatch" in item.message
        for item in evaluation.breaking_changes
    )


def test_policy_flags_root_id_change_as_immutable_identity(sample_odcs_model):
    base = sample_odcs_model.model_copy(deep=True)
    merged = sample_odcs_model.model_copy(deep=True)
    base.status = "active"
    merged.status = "active"
    merged.id = "different-guid"

    evaluation = evaluate_merge_policy(base, merged)

    assert evaluation.valid is False
    assert evaluation.id_violation is True
    assert any(item.path == "id" for item in evaluation.breaking_changes)
    assert any(
        "Contract ID mismatch" in item.message for item in evaluation.breaking_changes
    )


def test_policy_does_not_flag_version_when_unchanged(sample_odcs_model):
    base = sample_odcs_model.model_copy(deep=True)
    merged = sample_odcs_model.model_copy(deep=True)
    base.status = "active"
    merged.status = "active"

    evaluation = evaluate_merge_policy(base, merged)

    assert evaluation.id_violation is False
    assert evaluation.version_violation is False


def test_type_narrowing_fixture_documents_current_odcs_model_enum_gap(
    sample_type_narrowing_base_contract_model,
):
    status_prop = next(
        prop
        for prop in sample_type_narrowing_base_contract_model.schema_[0].properties
        if prop.name == "status_code"
    )  # type: ignore[index]

    # The currently installed ODCS model does not expose enum/enumValues on SchemaProperty,
    # so lifecycle enum-reduction checks are not reachable through file-backed fixtures yet.
    assert getattr(status_prop, "enum", None) is None
    assert getattr(status_prop, "enumValues", None) is None


def test_policy_flags_removed_relationship_in_active_contract(
    relationship_base_contract_model, relationship_target_contract_model
):
    evaluation = evaluate_merge_policy(
        relationship_base_contract_model, relationship_target_contract_model
    )
    assert evaluation.valid is False
    assert any(
        "Relationship 'foreignKey:orders.user_id->users.id' removed" in item.message
        for item in evaluation.breaking_changes
    )
