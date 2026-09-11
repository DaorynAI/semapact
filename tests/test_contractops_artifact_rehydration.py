from __future__ import annotations

from datetime import date

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)
from pydantic import ValidationError as PydanticValidationError

from semapact.change_context import ChangeContext
from semapact.contractops import (
    AppliedContractRelease,
    ChangeSet,
    ContractOpsAuthorization,
    PublicationResult,
    ReleasePlan,
    VersionAuthorityConfig,
    VersionResolution,
    apply_contract_release,
    authorize_contract_operation,
    build_change_set_from_decision,
    build_release_plan,
    publish_contract_release,
    resolve_release_version,
)
from semapact.governance import evaluate_governance_decision
from semapact.governance.gate import GovernanceOperation


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


class _Publisher:
    def publish(self, release: AppliedContractRelease) -> str:
        return f"registry:{release.applied_release_id}"


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
    apply_authorization = authorize_contract_operation(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.APPLY,
    )
    applied_release = apply_contract_release(
        candidate,
        candidate_revision_ref="git:candidate",
        decision=decision,
        change_set=change_set,
        release_plan=release_plan,
        version_resolution=version_resolution,
        authorization=apply_authorization,
    )
    publish_authorization = authorize_contract_operation(
        decision,
        change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.PUBLISH,
    )
    publication = publish_contract_release(
        applied_release,
        authorization=publish_authorization,
        publisher=_Publisher(),
    )
    return (
        change_set,
        release_plan,
        version_resolution,
        apply_authorization,
        applied_release,
        publication,
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
        authorization,
        applied_release,
        publication,
    ) = _artifact_chain()

    cases = (
        (ChangeSet, change_set, "candidate_revision_ref", "git:other"),
        (ReleasePlan, release_plan, "release_revision_ref", "git:other"),
        (VersionResolution, version_resolution, "release_revision_ref", "git:other"),
        (ContractOpsAuthorization, authorization, "decision_id", "decision:other"),
        (AppliedContractRelease, applied_release, "decision_id", "decision:other"),
        (PublicationResult, publication, "publication_reference", "registry:other"),
    )

    for model, artifact, field, tampered_value in cases:
        payload = artifact.model_dump(mode="json")
        payload[field] = tampered_value
        with pytest.raises(PydanticValidationError, match="deterministic identity"):
            model.model_validate(payload)
