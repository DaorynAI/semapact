from __future__ import annotations

import pytest
from open_data_contract_standard.model import (
    CustomProperty,
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.core.validator import ContractValidator
from semapact.lifecycle.status import (
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


def _cp(key: str, value: str) -> CustomProperty:
    return CustomProperty(property=key, value=value)


def test_normalize_status_valid_and_aliases():
    assert normalize_status("draft") is LifecycleStatus.DRAFT
    assert normalize_status("DRAFT") is LifecycleStatus.DRAFT
    assert normalize_status("  draft  ") is LifecycleStatus.DRAFT
    assert normalize_status("proposed") is LifecycleStatus.DRAFT
    assert normalize_status("PROPOSED") is LifecycleStatus.DRAFT
    assert normalize_status("active") is LifecycleStatus.ACTIVE
    assert normalize_status("Active") is LifecycleStatus.ACTIVE
    assert normalize_status("deprecated") is LifecycleStatus.DEPRECATED
    assert normalize_status("retired") is LifecycleStatus.RETIRED
    assert normalize_status(LifecycleStatus.ACTIVE) is LifecycleStatus.ACTIVE


def test_normalize_status_invalid_inputs():
    with pytest.raises(ValueError, match="cannot be None"):
        normalize_status(None)

    with pytest.raises(ValueError, match="cannot be empty"):
        normalize_status("")

    with pytest.raises(ValueError, match="cannot be empty"):
        normalize_status("   ")

    with pytest.raises(ValueError, match="Unknown lifecycle status: 'invalid_val'"):
        normalize_status("invalid_val")


def test_lifecycle_from_custom_properties():
    assert lifecycle_from_custom_properties(None) is None
    assert lifecycle_from_custom_properties([]) is None
    assert (
        lifecycle_from_custom_properties([_cp("description", "test")])
        is None
    )
    assert (
        lifecycle_from_custom_properties([_cp("lifecycleStatus", "active")])
        is LifecycleStatus.ACTIVE
    )
    assert (
        lifecycle_from_custom_properties([_cp("LIFECYCLESTATUS", "deprecated")])
        is LifecycleStatus.DEPRECATED
    )
    assert (
        lifecycle_from_custom_properties([{"property": "lifecycleStatus", "value": "retired"}])
        is LifecycleStatus.RETIRED
    )
    assert (
        lifecycle_from_custom_properties([_cp("lifecycleStatus", "")])
        is None
    )


def test_resolve_contract_lifecycle_precedence():
    # 1. Native root status
    c1 = OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="c1",
        version="1.0.0",
        status="active",
        customProperties=[_cp("lifecycleStatus", "deprecated")],
    )
    assert resolve_contract_lifecycle(c1) is LifecycleStatus.ACTIVE

    # 2. Legacy customProperties fallback when root status is missing
    c2 = OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="c2",
        version="1.0.0",
        customProperties=[_cp("lifecycleStatus", "deprecated")],
    )
    assert resolve_contract_lifecycle(c2) is LifecycleStatus.DEPRECATED

    # 3. Canonical default when neither is provided
    c3 = OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="c3",
        version="1.0.0",
    )
    assert resolve_contract_lifecycle(c3) is LifecycleStatus.DRAFT


def test_resolve_declared_entity_lifecycle():
    prop = SchemaProperty(name="col1")
    assert resolve_declared_entity_lifecycle(prop) is None

    prop_declared = SchemaProperty(
        name="col2",
        customProperties=[_cp("lifecycleStatus", "deprecated")],
    )
    assert resolve_declared_entity_lifecycle(prop_declared) is LifecycleStatus.DEPRECATED
    assert is_explicitly_deprecated(prop_declared) is True
    assert is_explicitly_deprecated(prop) is False


def test_contract_predicates():
    active_c = OpenDataContractStandard(
        apiVersion="v3.1.0", kind="DataContract", id="c", version="1.0.0", status="active"
    )
    retired_c = OpenDataContractStandard(
        apiVersion="v3.1.0", kind="DataContract", id="c", version="1.0.0", status="retired"
    )
    draft_c = OpenDataContractStandard(
        apiVersion="v3.1.0", kind="DataContract", id="c", version="1.0.0", status="draft"
    )

    assert is_active_contract(active_c) is True
    assert is_active_contract(retired_c) is False
    assert is_retired_contract(retired_c) is True
    assert is_retired_contract(active_c) is False
    assert is_active_contract(draft_c) is False


def test_participates_in_breaking_checks_predicate():
    assert participates_in_breaking_checks(LifecycleStatus.ACTIVE) is True
    assert participates_in_breaking_checks(LifecycleStatus.DRAFT) is False
    assert participates_in_breaking_checks(LifecycleStatus.DEPRECATED) is False
    assert participates_in_breaking_checks(LifecycleStatus.RETIRED) is False


def test_contract_validator_catches_invalid_lifecycle_statuses():
    validator = ContractValidator()

    # Invalid contract status
    invalid_contract = OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="test",
        version="1.0.0",
        status="non_existent_status",
    )
    report = validator.validate(invalid_contract)
    assert report.valid is False
    assert any("Invalid contract lifecycle status" in i.message for i in report.issues)

    # Invalid customProperties lifecycleStatus on property
    invalid_prop_contract = OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="test",
        version="1.0.0",
        status="active",
        schema=[
            SchemaObject(
                name="tbl",
                properties=[
                    SchemaProperty(
                        name="col",
                        customProperties=[_cp("lifecycleStatus", "bad_status")],
                    )
                ],
            )
        ],
    )
    report2 = validator.validate(invalid_prop_contract)
    assert report2.valid is False
    assert any("Invalid property customProperties lifecycleStatus" in i.message for i in report2.issues)


def test_resolve_schema_and_property_lifecycle_direct():
    active_contract = OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="c",
        version="1.0.0",
        status="active",
    )
    schema_default = SchemaObject(name="s")
    assert resolve_schema_lifecycle(schema_default, contract=active_contract) is LifecycleStatus.ACTIVE

    schema_deprecated = SchemaObject(
        name="s2", customProperties=[_cp("lifecycleStatus", "deprecated")]
    )
    assert resolve_schema_lifecycle(schema_deprecated, contract=active_contract) is LifecycleStatus.DEPRECATED

    prop_default = SchemaProperty(name="p")
    assert resolve_property_lifecycle(prop_default, parent_lifecycle=LifecycleStatus.ACTIVE) is LifecycleStatus.ACTIVE
    assert resolve_property_lifecycle(prop_default, parent_lifecycle=LifecycleStatus.DEPRECATED) is LifecycleStatus.DEPRECATED

    prop_draft = SchemaProperty(name="p2", customProperties=[_cp("lifecycleStatus", "draft")])
    assert resolve_property_lifecycle(prop_draft, parent_lifecycle=LifecycleStatus.ACTIVE) is LifecycleStatus.DRAFT

