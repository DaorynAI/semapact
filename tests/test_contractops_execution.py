from __future__ import annotations

from datetime import date

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.change_context import ChangeContext
from semapact.contractops import (
    VersionAuthorityConfig,
    build_change_set_from_decision,
    build_release_plan,
    build_release_snapshot,
    resolve_release_version,
)
from semapact.exceptions import ReleaseValidationError
from semapact.governance import evaluate_governance_decision


CONTEXT = ChangeContext(effective_date=date(2026, 9, 9))


def _contract(
    *,
    contract_id: str = "orders-product",
    contract_name: str = "orders",
    version: str = "1.0.0",
    include_created_at: bool = False,
) -> OpenDataContractStandard:
    properties = [
        SchemaProperty(
            name="id",
            logicalType="string",
            physicalType="varchar(255)",
            required=True,
        )
    ]
    if include_created_at:
        properties.append(
            SchemaProperty(
                name="created_at",
                logicalType="timestamp",
                physicalType="timestamp",
                required=False,
            )
        )
    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id=contract_id,
        name=contract_name,
        version=version,
        status="active",
        schema=[SchemaObject(name="orders", properties=properties)],
    )


def _release_context(*, include_created_at: bool = False):
    base = _contract(contract_name="orders-old")
    candidate = _contract(
        contract_name="orders-new",
        include_created_at=include_created_at,
    )
    decision = evaluate_governance_decision(base, candidate, context=CONTEXT)
    change_set = build_change_set_from_decision(
        decision,
        base_revision_ref="rev:base",
        candidate_revision_ref="rev:candidate",
        source="test",
        actor_reference="actor:test",
    )
    release_plan = build_release_plan(change_set, decision)
    version_resolution = resolve_release_version(
        release_plan,
        current_version="1.0.0",
        config=VersionAuthorityConfig(),
    )
    return candidate, decision, change_set, release_plan, version_resolution


def test_release_snapshot_is_deterministic_and_materializes_selected_version() -> None:
    candidate, decision, change_set, release_plan, version_resolution = (
        _release_context(include_created_at=True)
    )

    first = build_release_snapshot(
        candidate,
        candidate_revision_ref="rev:candidate",
        decision=decision,
        change_set=change_set,
        release_plan=release_plan,
        version_resolution=version_resolution,
    )
    second = build_release_snapshot(
        candidate,
        candidate_revision_ref="rev:candidate",
        decision=decision,
        change_set=change_set,
        release_plan=release_plan,
        version_resolution=version_resolution,
    )

    assert first == second
    assert first.release_snapshot_id == second.release_snapshot_id
    assert first.selected_version == version_resolution.selected_version
    assert first.to_contract().version == version_resolution.selected_version
    assert first.to_contract().name == "orders-new"
    assert candidate.version == "1.0.0"
    assert not hasattr(first, "authorization_id")


def test_release_snapshot_fails_closed_for_stale_candidate_revision() -> None:
    candidate, decision, change_set, release_plan, version_resolution = (
        _release_context()
    )

    with pytest.raises(ReleaseValidationError, match="planned release revision"):
        build_release_snapshot(
            candidate,
            candidate_revision_ref="rev:stale",
            decision=decision,
            change_set=change_set,
            release_plan=release_plan,
            version_resolution=version_resolution,
        )


def test_release_snapshot_fails_closed_when_candidate_version_drifted() -> None:
    candidate, decision, change_set, release_plan, version_resolution = (
        _release_context()
    )
    drifted_candidate = candidate.model_copy(deep=True)
    drifted_candidate.version = "9.0.0"

    with pytest.raises(ReleaseValidationError, match="current_version"):
        build_release_snapshot(
            drifted_candidate,
            candidate_revision_ref="rev:candidate",
            decision=decision,
            change_set=change_set,
            release_plan=release_plan,
            version_resolution=version_resolution,
        )


def test_release_snapshot_rejects_noncanonical_semver_input() -> None:
    candidate, decision, change_set, release_plan, version_resolution = (
        _release_context()
    )
    drifted_resolution = version_resolution.model_copy(
        update={"selected_version": "v1.0.1"}
    )

    with pytest.raises(ReleaseValidationError, match="canonical"):
        build_release_snapshot(
            candidate,
            candidate_revision_ref="rev:candidate",
            decision=decision,
            change_set=change_set,
            release_plan=release_plan,
            version_resolution=drifted_resolution,
        )
