from __future__ import annotations

from datetime import datetime, timezone

from semapact.observation.fingerprint import (
    canonical_observed_state_payload,
    fingerprint_observed_state,
    with_observed_state_fingerprint,
)
from semapact.observation.models import (
    ObservedAsset,
    ObservedAssetIdentity,
    ObservedPlatformState,
    ObservedProperty,
    ObservedPropertyIdentity,
)

CAPTURED_AT = datetime(2026, 8, 30, 3, 0, tzinfo=timezone.utc)


def _orders_asset(
    *,
    platform: str = "databricks",
    namespace: tuple[str, ...] = ("main", "silver"),
    asset_name: str = "orders",
    property_order: tuple[str, ...] = ("order_id", "customer_id", "note"),
    physical_types: dict[str, str] | None = None,
    nullable: dict[str, bool | None] | None = None,
    asset_type: str = "MANAGED",
) -> ObservedAsset:
    identity = ObservedAssetIdentity(
        platform=platform,
        namespace=namespace,
        asset=asset_name,
    )
    types = physical_types or {
        "order_id": "bigint",
        "customer_id": "string",
        "note": "string",
    }
    nullability = nullable or {
        "order_id": False,
        "customer_id": False,
        "note": True,
    }
    return ObservedAsset(
        identity=identity,
        asset_type=asset_type,
        properties=tuple(
            ObservedProperty(
                identity=ObservedPropertyIdentity(asset=identity, property=name),
                physical_type=types[name],
                nullable=nullability[name],
            )
            for name in property_order
        ),
    )


def _state(
    *,
    assets: tuple[ObservedAsset, ...] | None = None,
    platform: str = "databricks",
    source_identifier: str = "https://adb.example",
    captured_at: datetime = CAPTURED_AT,
    fingerprint: str | None = None,
) -> ObservedPlatformState:
    return ObservedPlatformState(
        platform=platform,
        source_identifier=source_identifier,
        assets=assets or (_orders_asset(),),
        captured_at=captured_at,
        fingerprint=fingerprint,
    )


def test_observed_state_fingerprint_has_stable_versioned_golden_value() -> None:
    state = _state()

    assert fingerprint_observed_state(state) == (
        "obs-v1:sha256:"
        "cc72fb5e20b673784b0847f6f903c05178b88c3d88ffb25f830da0a373457287"
    )
    assert canonical_observed_state_payload(state)["fingerprint_version"] == "obs-v1"


def test_observation_envelope_fields_do_not_change_semantic_fingerprint() -> None:
    baseline = _state()
    later = _state(
        source_identifier="workspace-alias-b",
        captured_at=datetime(2026, 8, 31, 4, 30, tzinfo=timezone.utc),
        fingerprint="previous-value",
    )

    assert fingerprint_observed_state(baseline) == fingerprint_observed_state(later)


def test_asset_property_order_and_identity_case_do_not_change_fingerprint() -> None:
    first = _orders_asset()
    second_identity = ObservedAssetIdentity(
        platform="databricks",
        namespace=("main", "silver"),
        asset="customers",
    )
    second = ObservedAsset(identity=second_identity, asset_type="MANAGED")

    reordered = _orders_asset(
        platform="DATABRICKS",
        namespace=("MAIN", "SILVER"),
        asset_name="ORDERS",
        property_order=("note", "customer_id", "order_id"),
    )

    left = _state(assets=(first, second))
    right = _state(platform="DATABRICKS", assets=(second, reordered))

    assert fingerprint_observed_state(left) == fingerprint_observed_state(right)


def test_governance_relevant_observed_changes_change_fingerprint() -> None:
    baseline = fingerprint_observed_state(_state())

    changed_asset_type = _state(assets=(_orders_asset(asset_type="EXTERNAL"),))
    changed_property_type = _state(
        assets=(
            _orders_asset(
                physical_types={
                    "order_id": "string",
                    "customer_id": "string",
                    "note": "string",
                }
            ),
        )
    )
    changed_nullability = _state(
        assets=(
            _orders_asset(
                nullable={
                    "order_id": True,
                    "customer_id": False,
                    "note": True,
                }
            ),
        )
    )
    changed_property_identity = _state(
        assets=(
            _orders_asset(
                property_order=("order_id", "customer_id", "comment"),
                physical_types={
                    "order_id": "bigint",
                    "customer_id": "string",
                    "comment": "string",
                },
                nullable={
                    "order_id": False,
                    "customer_id": False,
                    "comment": True,
                },
            ),
        )
    )

    assert fingerprint_observed_state(changed_asset_type) != baseline
    assert fingerprint_observed_state(changed_property_type) != baseline
    assert fingerprint_observed_state(changed_nullability) != baseline
    assert fingerprint_observed_state(changed_property_identity) != baseline


def test_with_observed_state_fingerprint_returns_immutable_copy() -> None:
    state = _state()

    fingerprinted = with_observed_state_fingerprint(state)

    assert state.fingerprint is None
    assert fingerprinted is not state
    assert fingerprinted.fingerprint == fingerprint_observed_state(state)
