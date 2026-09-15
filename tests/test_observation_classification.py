from __future__ import annotations

import inspect
from datetime import datetime, timezone

from semapact.observation import classification, fingerprint, models, providers
from semapact.observation.classification import (
    ObservedEvidenceClass,
    ObservedEvidenceKind,
    classify_observed_evidence,
    summarize_observed_evidence,
)
from semapact.observation.models import (
    ObservedAsset,
    ObservedAssetIdentity,
    ObservedConstraint,
    ObservedConstraintKind,
    ObservedPlatformState,
    ObservedProperty,
    ObservedPropertyIdentity,
    ObservedRelationship,
    ObservedRelationshipKind,
    ObservedTag,
)

CAPTURED_AT = datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc)


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
    assert {item.evidence_class: item.count for item in metrics.by_class} == {
        ObservedEvidenceClass.STRUCTURAL: 5,
        ObservedEvidenceClass.SEMANTIC: 5,
        ObservedEvidenceClass.OPERATIONAL: 1,
    }


def test_equivalent_platform_observations_receive_the_same_metrics() -> None:
    first = summarize_observed_evidence(_state("platform-a"))
    second = summarize_observed_evidence(_state("platform-b"))

    assert first == second


def test_observation_core_does_not_depend_on_platform_adapters() -> None:
    for module in (classification, fingerprint, models, providers):
        assert "semapact.platforms" not in inspect.getsource(module)
