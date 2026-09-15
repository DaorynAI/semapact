from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from semapact.observation import canonical, classification, evidence, fingerprint, models, providers
from semapact.observation import (
    ObservedAsset,
    ObservedAssetIdentity,
    ObservedConstraint,
    ObservedConstraintKind,
    ObservedEvidenceAvailability,
    ObservedEvidenceAvailabilityStatus,
    ObservedEvidenceClass,
    ObservedEvidenceKind,
    ObservedPlatformState,
    ObservedProperty,
    ObservedPropertyIdentity,
    ObservedRelationship,
    ObservedRelationshipKind,
    ObservedTag,
    classify_observed_evidence,
    summarize_observed_evidence,
)

CAPTURED_AT = datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc)


def _availability(
    *,
    tag_status: ObservedEvidenceAvailabilityStatus = ObservedEvidenceAvailabilityStatus.AVAILABLE,
) -> tuple[ObservedEvidenceAvailability, ...]:
    return tuple(
        ObservedEvidenceAvailability(
            kind=kind,
            status=(
                tag_status
                if kind is ObservedEvidenceKind.TAG
                else ObservedEvidenceAvailabilityStatus.AVAILABLE
            ),
        )
        for kind in ObservedEvidenceKind
    )


def _state(platform: str) -> ObservedPlatformState:
    asset_identity = ObservedAssetIdentity(
        platform=platform,
        namespace=("governed",),
        asset="orders",
    )
    target_identity = ObservedAssetIdentity(
        platform=platform,
        namespace=("governed",),
        asset="customers",
    )
    properties = (
        ObservedProperty(
            identity=ObservedPropertyIdentity(asset=asset_identity, property="order_id"),
            physical_type="bigint",
            nullable=False,
            comment="Order identifier",
            tags=(ObservedTag(key="Identifier", value="true"),),
        ),
        ObservedProperty(
            identity=ObservedPropertyIdentity(asset=asset_identity, property="customer_id"),
            physical_type="string",
            nullable=False,
        ),
    )
    asset = ObservedAsset(
        identity=asset_identity,
        asset_type="TABLE",
        owner="data-team@example.com",
        comment="Orders",
        tags=(
            ObservedTag(key="Domain", value="Sales"),
            ObservedTag(key="Sensitivity", value="Internal"),
        ),
        properties=properties,
        constraints=(
            ObservedConstraint(
                kind=ObservedConstraintKind.PRIMARY_KEY,
                properties=("order_id",),
            ),
        ),
        relationships=(
            ObservedRelationship(
                kind=ObservedRelationshipKind.FOREIGN_KEY,
                source_asset=asset_identity,
                source_properties=("customer_id",),
                target_asset=target_identity,
                target_properties=("customer_id",),
            ),
        ),
    )
    return ObservedPlatformState(
        platform=platform,
        source_identifier="test-source",
        assets=(asset,),
        captured_at=CAPTURED_AT,
        evidence_availability=_availability(),
    )


def test_classification_is_provider_neutral_and_complete() -> None:
    expected = {
        ObservedEvidenceKind.PHYSICAL_SCHEMA: ObservedEvidenceClass.STRUCTURAL,
        ObservedEvidenceKind.OWNER: ObservedEvidenceClass.OPERATIONAL,
        ObservedEvidenceKind.COMMENT: ObservedEvidenceClass.SEMANTIC,
        ObservedEvidenceKind.TAG: ObservedEvidenceClass.SEMANTIC,
        ObservedEvidenceKind.CONSTRAINT: ObservedEvidenceClass.STRUCTURAL,
        ObservedEvidenceKind.RELATIONSHIP: ObservedEvidenceClass.STRUCTURAL,
    }

    assert {
        kind: classify_observed_evidence(kind) for kind in ObservedEvidenceKind
    } == expected


def test_standard_metrics_are_derived_from_canonical_observation() -> None:
    metrics = summarize_observed_evidence(_state("example-platform"))

    assert metrics.total == 11
    assert {item.kind: item.count for item in metrics.by_kind} == {
        ObservedEvidenceKind.PHYSICAL_SCHEMA: 3,
        ObservedEvidenceKind.OWNER: 1,
        ObservedEvidenceKind.COMMENT: 2,
        ObservedEvidenceKind.TAG: 3,
        ObservedEvidenceKind.CONSTRAINT: 1,
        ObservedEvidenceKind.RELATIONSHIP: 1,
    }
    assert all(
        item.availability is ObservedEvidenceAvailabilityStatus.AVAILABLE
        for item in metrics.by_kind
    )
    assert {item.evidence_class: item.count for item in metrics.by_class} == {
        ObservedEvidenceClass.STRUCTURAL: 5,
        ObservedEvidenceClass.SEMANTIC: 5,
        ObservedEvidenceClass.OPERATIONAL: 1,
    }


def test_zero_count_is_distinct_from_unavailable_evidence() -> None:
    identity = ObservedAssetIdentity(platform="example", asset="orders")
    asset = ObservedAsset(identity=identity)
    available = ObservedPlatformState(
        platform="example",
        source_identifier="source",
        assets=(asset,),
        captured_at=CAPTURED_AT,
        evidence_availability=_availability(),
    )
    unavailable = available.model_copy(
        update={
            "evidence_availability": _availability(
                tag_status=ObservedEvidenceAvailabilityStatus.UNAVAILABLE
            )
        }
    )

    available_tag = next(
        item
        for item in summarize_observed_evidence(available).by_kind
        if item.kind is ObservedEvidenceKind.TAG
    )
    unavailable_tag = next(
        item
        for item in summarize_observed_evidence(unavailable).by_kind
        if item.kind is ObservedEvidenceKind.TAG
    )

    assert available_tag.count == unavailable_tag.count == 0
    assert available_tag.availability is ObservedEvidenceAvailabilityStatus.AVAILABLE
    assert unavailable_tag.availability is ObservedEvidenceAvailabilityStatus.UNAVAILABLE


def test_equivalent_platform_observations_receive_the_same_metrics() -> None:
    first = summarize_observed_evidence(_state("platform-a"))
    second = summarize_observed_evidence(_state("platform-b"))

    assert first == second


def test_canonical_observation_rejects_nested_identity_mismatch() -> None:
    container = ObservedAssetIdentity(platform="example", asset="orders")
    other = ObservedAssetIdentity(platform="example", asset="customers")

    with pytest.raises(ValidationError, match="containing asset"):
        ObservedAsset(
            identity=container,
            properties=(
                ObservedProperty(
                    identity=ObservedPropertyIdentity(asset=other, property="id")
                ),
            ),
        )


def test_canonical_observation_rejects_platform_mismatch() -> None:
    with pytest.raises(ValidationError, match="platform must match"):
        ObservedPlatformState(
            platform="platform-a",
            source_identifier="source",
            assets=(
                ObservedAsset(
                    identity=ObservedAssetIdentity(platform="platform-b", asset="orders")
                ),
            ),
            captured_at=CAPTURED_AT,
        )


def test_observation_core_does_not_depend_on_platform_adapters() -> None:
    for module in (canonical, classification, evidence, fingerprint, models, providers):
        assert "semapact.platforms" not in inspect.getsource(module)
