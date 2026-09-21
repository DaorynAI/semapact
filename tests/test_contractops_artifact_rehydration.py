from __future__ import annotations

import json
from datetime import date

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)
from pydantic import ValidationError as PydanticValidationError

from semapact.application.models.release import (
    build_contract_release,
    build_release_bundle,
)
from semapact.change_context import ChangeContext
from semapact.contractops import (
    ChangeSet,
    ContractRelease,
    ReleasePlan,
    ReleaseSnapshot,
    VersionAuthorityConfig,
    VersionResolution,
    build_change_set_from_decision,
    build_release_plan,
    build_release_snapshot,
    resolve_release_version,
)
from semapact.governance import evaluate_governance_decision


CONTEXT = ChangeContext(effective_date=date(2026, 9, 11))


def _contract(*, name: str) -> OpenDataContractStandard:
    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="orders-product",
        name=name,
        version="1.0.0",
        status="active",
        schema=[
            SchemaObject(
                name="orders",
                properties=[
                    SchemaProperty(
                        name="id",
                        logicalType="string",
                        physicalType="varchar(255)",
                        required=True,
                    )
                ],
            )
        ],
    )


def _artifact_chain():
    base = _contract(name="orders-old")
    candidate = _contract(name="orders-new")
    decision = evaluate_governance_decision(base, candidate, context=CONTEXT)
    change_set = build_change_set_from_decision(
        decision,
        base_revision_ref="git:base",
        candidate_revision_ref="git:candidate",
        source="rehydration-test",
        actor_reference="service:ci",
    )
    release_plan = build_release_plan(change_set, decision)
    version_resolution = resolve_release_version(
        release_plan,
        current_version="1.0.0",
        config=VersionAuthorityConfig(),
    )
    snapshot = build_release_snapshot(
        candidate,
        candidate_revision_ref="git:candidate",
        decision=decision,
        change_set=change_set,
        release_plan=release_plan,
        version_resolution=version_resolution,
    )
    bundle = build_release_bundle(
        decision=decision,
        change_set=change_set,
        release_plan=release_plan,
        version_resolution=version_resolution,
        release_snapshot=snapshot,
    )
    contract_release = build_contract_release(bundle)
    return (
        change_set,
        release_plan,
        version_resolution,
        snapshot,
        contract_release,
    )


def test_identity_bearing_artifacts_round_trip_through_json() -> None:
    artifacts = _artifact_chain()

    for artifact in artifacts:
        rehydrated = type(artifact).model_validate_json(artifact.model_dump_json())
        assert rehydrated == artifact


def test_rehydration_rejects_content_with_stale_deterministic_identity() -> None:
    (
        change_set,
        release_plan,
        version_resolution,
        snapshot,
        contract_release,
    ) = _artifact_chain()

    cases = (
        (ChangeSet, change_set, "candidate_revision_ref", "git:other"),
        (ReleasePlan, release_plan, "release_revision_ref", "git:other"),
        (VersionResolution, version_resolution, "release_revision_ref", "git:other"),
        (ReleaseSnapshot, snapshot, "decision_id", "decision:other"),
        (ContractRelease, contract_release, "source_revision_ref", "git:other"),
    )

    for model, artifact, field, tampered_value in cases:
        payload = artifact.model_dump(mode="json")
        payload[field] = tampered_value
        persisted_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        with pytest.raises(
            (PydanticValidationError, ValueError),
            match="deterministic identity|does not match",
        ):
            model.model_validate_json(persisted_json)
