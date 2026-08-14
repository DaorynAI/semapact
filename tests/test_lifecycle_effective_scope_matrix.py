from __future__ import annotations

import pytest
from open_data_contract_standard.model import (
    CustomProperty,
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.lifecycle.status import (
    LifecycleStatus,
    participates_in_breaking_checks,
    resolve_contract_lifecycle,
    resolve_property_lifecycle,
    resolve_schema_lifecycle,
)


def _cp(key: str, value: str) -> CustomProperty:
    return CustomProperty(property=key, value=value)


@pytest.mark.parametrize(
    (
        "contract_status",
        "schema_declared",
        "prop_declared",
        "nested_declared",
        "expected_schema_effective",
        "expected_prop_effective",
        "expected_nested_effective",
        "expected_breaking_checks",
    ),
    [
        # 1. Fully active unannotated hierarchy
        (
            "active",
            None,
            None,
            None,
            LifecycleStatus.ACTIVE,
            LifecycleStatus.ACTIVE,
            LifecycleStatus.ACTIVE,
            True,
        ),
        # 2. Schema draft: child active cannot reactivate past draft schema
        (
            "active",
            "draft",
            "active",
            "active",
            LifecycleStatus.DRAFT,
            LifecycleStatus.DRAFT,
            LifecycleStatus.DRAFT,
            False,
        ),
        # 3. Schema deprecated: child active cannot reactivate past deprecated schema
        (
            "active",
            "deprecated",
            "active",
            "active",
            LifecycleStatus.DEPRECATED,
            LifecycleStatus.DEPRECATED,
            LifecycleStatus.DEPRECATED,
            False,
        ),
        # 4. Property deprecated: nested active child cannot reactivate past deprecated parent property
        (
            "active",
            "active",
            "deprecated",
            "active",
            LifecycleStatus.ACTIVE,
            LifecycleStatus.DEPRECATED,
            LifecycleStatus.DEPRECATED,
            False,  # for nested child
        ),
        # 5. Property draft: nested active child cannot reactivate past draft parent property
        (
            "active",
            "active",
            "draft",
            "active",
            LifecycleStatus.ACTIVE,
            LifecycleStatus.DRAFT,
            LifecycleStatus.DRAFT,
            False,  # for nested child
        ),
        # 6. Contract draft: entire subtree is draft
        (
            "draft",
            "active",
            "active",
            "active",
            LifecycleStatus.DRAFT,
            LifecycleStatus.DRAFT,
            LifecycleStatus.DRAFT,
            False,
        ),
        # 7. Contract retired: entire subtree is retired
        (
            "retired",
            "active",
            "active",
            "active",
            LifecycleStatus.RETIRED,
            LifecycleStatus.RETIRED,
            LifecycleStatus.RETIRED,
            False,
        ),
        # 8. Contract deprecated: entire subtree is deprecated
        (
            "deprecated",
            "active",
            "active",
            "active",
            LifecycleStatus.DEPRECATED,
            LifecycleStatus.DEPRECATED,
            LifecycleStatus.DEPRECATED,
            False,
        ),
        # 9. Proposed contract alias: interpreted as draft
        (
            "proposed",
            None,
            None,
            None,
            LifecycleStatus.DRAFT,
            LifecycleStatus.DRAFT,
            LifecycleStatus.DRAFT,
            False,
        ),
    ],
)
def test_lifecycle_effective_scope_matrix(
    contract_status: str,
    schema_declared: str | None,
    prop_declared: str | None,
    nested_declared: str | None,
    expected_schema_effective: LifecycleStatus,
    expected_prop_effective: LifecycleStatus,
    expected_nested_effective: LifecycleStatus,
    expected_breaking_checks: bool,
):
    nested_cp = [_cp("lifecycleStatus", nested_declared)] if nested_declared else []
    nested_prop = SchemaProperty(name="street", customProperties=nested_cp)

    prop_cp = [_cp("lifecycleStatus", prop_declared)] if prop_declared else []
    top_prop = SchemaProperty(
        name="address",
        customProperties=prop_cp,
        properties=[nested_prop],
    )

    schema_cp = [_cp("lifecycleStatus", schema_declared)] if schema_declared else []
    schema_obj = SchemaObject(
        name="customers",
        customProperties=schema_cp,
        properties=[top_prop],
    )

    contract = OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="c1",
        version="1.0.0",
        status=contract_status,
        schema=[schema_obj],
    )

    # 1. Resolve contract
    eff_contract = resolve_contract_lifecycle(contract)
    assert eff_contract is not None

    # 2. Resolve schema
    eff_schema = resolve_schema_lifecycle(schema_obj, contract=contract)

    assert eff_schema is expected_schema_effective

    # 3. Resolve top-level property
    eff_top_prop = resolve_property_lifecycle(top_prop, parent_lifecycle=eff_schema)
    assert eff_top_prop is expected_prop_effective

    # 4. Resolve nested child property
    eff_nested_prop = resolve_property_lifecycle(nested_prop, parent_lifecycle=eff_top_prop)
    assert eff_nested_prop is expected_nested_effective

    # 5. Check breaking checks predicate on the deepest child
    assert participates_in_breaking_checks(eff_nested_prop) is expected_breaking_checks
