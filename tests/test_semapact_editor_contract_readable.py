from __future__ import annotations

from open_data_contract_standard.model import (
    CustomProperty,
    OpenDataContractStandard,
    SchemaProperty,
)

from semapact.core.editor_contract import (
    contract_description_part,
    contract_tags,
    field_examples_text,
    field_lifecycle_status,
)
from semapact.core.editor_semantics import (
    contract_api_version,
    contract_data_product,
    contract_domain,
    contract_id,
    contract_kind,
    contract_name,
    contract_status,
    contract_tenant,
    contract_version,
)


def test_contract_description_and_tags_support_dict_and_odcs_model(
    sample_odcs_dict, sample_odcs_model
):
    sample_odcs_dict["tags"] = ["finance", "Finance", "critical"]
    purpose_from_dict = contract_description_part(sample_odcs_dict, "purpose")
    tags_from_dict = contract_tags(sample_odcs_dict)

    refreshed_model = OpenDataContractStandard.model_validate(sample_odcs_dict)
    purpose_from_model = contract_description_part(refreshed_model, "purpose")
    tags_from_model = contract_tags(refreshed_model)

    assert purpose_from_dict == purpose_from_model
    assert tags_from_dict == ["finance", "critical"]
    assert tags_from_model == ["finance", "critical"]


def test_contract_accessors_support_dict_and_odcs_model(sample_odcs_dict):
    sample_odcs_dict["name"] = "seller_payments_contract"
    sample_odcs_dict["tenant"] = "tenant-a"
    sample_odcs_dict["status"] = "active"
    sample_odcs_dict["domain"] = "seller"
    sample_odcs_dict["dataProduct"] = "seller payments"
    model = OpenDataContractStandard.model_validate(sample_odcs_dict)

    assert (
        contract_name(sample_odcs_dict)
        == contract_name(model)
        == "seller_payments_contract"
    )
    assert (
        contract_version(sample_odcs_dict)
        == contract_version(model)
        == str(sample_odcs_dict["version"])
    )
    assert contract_status(sample_odcs_dict) == contract_status(model) == "active"
    assert contract_domain(sample_odcs_dict) == contract_domain(model) == "seller"
    assert (
        contract_data_product(sample_odcs_dict)
        == contract_data_product(model)
        == "seller payments"
    )
    assert contract_tenant(sample_odcs_dict) == contract_tenant(model) == "tenant-a"
    assert (
        contract_id(sample_odcs_dict)
        == contract_id(model)
        == str(sample_odcs_dict["id"])
    )
    assert (
        contract_api_version(sample_odcs_dict)
        == contract_api_version(model)
        == str(sample_odcs_dict["apiVersion"])
    )
    assert (
        contract_kind(sample_odcs_dict)
        == contract_kind(model)
        == str(sample_odcs_dict["kind"])
    )


def test_field_helpers_support_odcs_model_and_ui_working_copy():
    field_model = SchemaProperty(
        name="payment_id",
        examples=["a", "b"],
        customProperties=[CustomProperty(property="lifecycleStatus", value="active")],
    )
    field_dict = {
        "name": "payment_id",
        "examples": ["c", "d"],
        "customProperties": [{"property": "lifecycleStatus", "value": "deprecated"}],
    }

    assert field_lifecycle_status(field_model) == "active"
    assert field_lifecycle_status(field_dict) == "deprecated"
    assert field_examples_text(field_model) == "a\nb"
    assert field_examples_text(field_dict) == "c\nd"

