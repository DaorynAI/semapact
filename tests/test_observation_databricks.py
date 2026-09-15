from __future__ import annotations

import inspect
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from semapact.observation import (
    ObservedEvidenceAvailabilityStatus,
    ObservedEvidenceKind,
    summarize_observed_evidence,
)
from semapact.observation.models import (
    ObservedConstraintKind,
    ObservedPlatformState,
    ObservedRelationshipDirection,
    ObservedRelationshipKind,
    serialize_observed_state,
)
from semapact.platforms.databricks import observation as databricks_observation
from semapact.platforms.databricks.observation import (
    map_databricks_table_info,
    observe_databricks_table,
)

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "observation"
    / "databricks"
    / "orders_table_info.json"
)
CAPTURED_AT = datetime(2026, 8, 30, 3, 0, tzinfo=timezone.utc)


def _payload() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class _FakeSdkObject:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def as_dict(self) -> dict[str, object]:
        return self._payload


class _FakeTablesApi:
    def __init__(self, table: _FakeSdkObject) -> None:
        self._table = table
        self.calls: list[str] = []

    def get(self, full_name: str) -> _FakeSdkObject:
        self.calls.append(full_name)
        return self._table


class _FakeEntityTagsApi:
    def __init__(self, assignments: dict[tuple[str, str], list[dict[str, object]]]) -> None:
        self._assignments = assignments
        self.calls: list[tuple[str, str]] = []

    def list(self, entity_type: str, entity_name: str):
        self.calls.append((entity_type, entity_name))
        return (
            _FakeSdkObject(item)
            for item in self._assignments.get((entity_type, entity_name), [])
        )


class _FakeWorkspaceClient:
    def __init__(
        self,
        table: _FakeSdkObject,
        *,
        assignments: dict[tuple[str, str], list[dict[str, object]]] | None = None,
    ) -> None:
        self.tables = _FakeTablesApi(table)
        if assignments is not None:
            self.entity_tag_assignments = _FakeEntityTagsApi(assignments)


def _availability_by_kind(state: ObservedPlatformState):
    return {item.kind: item.status for item in state.evidence_availability}


def test_databricks_table_info_maps_to_platform_neutral_observation() -> None:
    state = map_databricks_table_info(
        _FakeSdkObject(_payload()),
        source_identifier="https://adb.example/",
        captured_at=CAPTURED_AT,
    )

    assert isinstance(state, ObservedPlatformState)
    assert state.platform == "databricks"
    assert state.source_identifier == "https://adb.example"
    assert state.captured_at == CAPTURED_AT
    assert state.fingerprint == (
        "obs-v2:sha256:"
        "85fd6b22461aa53d25d0c55e35235ff9c7c544f96e88e5d9c67f9051cb6e7bc7"
    )

    availability = _availability_by_kind(state)
    assert availability[ObservedEvidenceKind.PHYSICAL_SCHEMA] is ObservedEvidenceAvailabilityStatus.AVAILABLE
    assert availability[ObservedEvidenceKind.OWNER] is ObservedEvidenceAvailabilityStatus.AVAILABLE
    assert availability[ObservedEvidenceKind.COMMENT] is ObservedEvidenceAvailabilityStatus.AVAILABLE
    assert availability[ObservedEvidenceKind.TAG] is ObservedEvidenceAvailabilityStatus.UNKNOWN
    assert availability[ObservedEvidenceKind.CONSTRAINT] is ObservedEvidenceAvailabilityStatus.AVAILABLE
    assert availability[ObservedEvidenceKind.RELATIONSHIP] is ObservedEvidenceAvailabilityStatus.AVAILABLE

    assert len(state.assets) == 1
    asset = state.assets[0]
    assert asset.identity.platform == "databricks"
    assert asset.identity.namespace == ("main", "silver")
    assert asset.identity.asset == "orders"
    assert asset.identity.canonical_key == (
        "databricks",
        "main",
        "silver",
        "orders",
    )
    assert asset.asset_type == "MANAGED"
    assert asset.owner == "data-platform@example.com"
    assert asset.comment == "Curated customer orders"

    assert [item.identity.property for item in asset.properties] == [
        "order_id",
        "customer_id",
        "note",
    ]
    assert asset.properties[0].physical_type == "bigint"
    assert asset.properties[0].nullable is False
    assert asset.properties[0].comment == "Order business identifier"
    assert asset.properties[1].physical_type == "string"
    assert asset.properties[1].comment == "Customer business identifier"
    assert asset.properties[2].nullable is True

    assert [item.kind for item in asset.constraints] == [
        ObservedConstraintKind.NAMED,
        ObservedConstraintKind.PRIMARY_KEY,
    ]
    primary_key = next(
        item for item in asset.constraints if item.kind is ObservedConstraintKind.PRIMARY_KEY
    )
    assert primary_key.name == "pk_orders"
    assert primary_key.properties == ("order_id",)
    assert primary_key.provenance == "unity_catalog"

    assert len(asset.relationships) == 1
    relationship = asset.relationships[0]
    assert relationship.kind is ObservedRelationshipKind.FOREIGN_KEY
    assert relationship.direction is ObservedRelationshipDirection.OUTBOUND
    assert relationship.name == "fk_orders_customer"
    assert relationship.source_asset == asset.identity
    assert relationship.source_properties == ("customer_id",)
    assert relationship.target_asset is not None
    assert relationship.target_asset.namespace == ("main", "silver")
    assert relationship.target_asset.asset == "customers"
    assert relationship.target_properties == ("customer_id",)
    assert relationship.target_reference == "main.silver.customers"
    assert relationship.provenance == "unity_catalog"


def test_observation_model_identity_does_not_encode_databricks_namespace_names() -> None:
    state = map_databricks_table_info(
        _FakeSdkObject(_payload()),
        source_identifier="workspace-a",
        captured_at=CAPTURED_AT,
    )

    identity_fields = set(type(state.assets[0].identity).model_fields)
    assert identity_fields == {"platform", "namespace", "asset"}
    assert "catalog" not in identity_fields
    assert "schema" not in identity_fields


def test_serialization_is_stable_when_databricks_payload_order_changes() -> None:
    payload = _payload()
    reordered = dict(payload)
    reordered["columns"] = list(reversed(payload["columns"]))  # type: ignore[index]
    reordered["table_constraints"] = list(  # type: ignore[index]
        reversed(payload["table_constraints"])  # type: ignore[index]
    )

    left = map_databricks_table_info(
        _FakeSdkObject(payload),
        source_identifier="https://adb.example",
        captured_at=CAPTURED_AT,
    )
    right = map_databricks_table_info(
        _FakeSdkObject(reordered),
        source_identifier="https://adb.example",
        captured_at=CAPTURED_AT,
    )

    assert left == right
    assert left.fingerprint == right.fingerprint
    assert serialize_observed_state(left) == serialize_observed_state(right)


def test_observe_databricks_table_reads_and_normalizes_table_and_column_tags() -> None:
    assignments = {
        ("tables", "main.silver.orders"): [
            {"tag_key": "Domain", "tag_value": "Sales"},
            {"tag_key": "Sensitivity", "tag_value": "Internal"},
            {"tag_key": "Domain", "tag_value": "Sales"},
        ],
        ("columns", "main.silver.orders.customer_id"): [
            {"tag_key": "PII", "tag_value": "true"},
        ],
    }
    client = _FakeWorkspaceClient(_FakeSdkObject(_payload()), assignments=assignments)

    state = observe_databricks_table(
        client=client,
        table_fqn="main.silver.orders",
        source_identifier="https://adb.example",
        captured_at=CAPTURED_AT,
    )

    assert client.tables.calls == ["main.silver.orders"]
    assert state.assets[0].identity.asset == "orders"
    assert [(item.key, item.value) for item in state.assets[0].tags] == [
        ("Domain", "Sales"),
        ("Sensitivity", "Internal"),
    ]
    customer = next(
        item for item in state.assets[0].properties if item.identity.property == "customer_id"
    )
    assert [(item.key, item.value) for item in customer.tags] == [("PII", "true")]
    assert all(item.provenance == "unity_catalog" for item in state.assets[0].tags)
    assert state.fingerprint is not None
    metrics = summarize_observed_evidence(state)
    tag_metric = next(item for item in metrics.by_kind if item.kind is ObservedEvidenceKind.TAG)
    assert tag_metric.availability is ObservedEvidenceAvailabilityStatus.AVAILABLE
    assert tag_metric.count == 3

    tag_calls = client.entity_tag_assignments.calls
    assert ("tables", "main.silver.orders") in tag_calls
    assert ("columns", "main.silver.orders.order_id") in tag_calls
    assert ("columns", "main.silver.orders.customer_id") in tag_calls
    assert ("columns", "main.silver.orders.note") in tag_calls


def test_tag_api_iteration_order_does_not_change_observation() -> None:
    ordered = [
        {"tag_key": "A", "tag_value": "1"},
        {"tag_key": "B", "tag_value": "2"},
    ]
    left = _FakeWorkspaceClient(
        _FakeSdkObject(_payload()),
        assignments={("tables", "main.silver.orders"): ordered},
    )
    right = _FakeWorkspaceClient(
        _FakeSdkObject(_payload()),
        assignments={("tables", "main.silver.orders"): list(reversed(ordered))},
    )

    first = observe_databricks_table(
        client=left,
        table_fqn="main.silver.orders",
        source_identifier="workspace-a",
        captured_at=CAPTURED_AT,
    )
    second = observe_databricks_table(
        client=right,
        table_fqn="main.silver.orders",
        source_identifier="workspace-a",
        captured_at=CAPTURED_AT,
    )

    assert first == second
    assert first.fingerprint == second.fingerprint


def test_observe_databricks_table_marks_missing_tag_capability_unavailable() -> None:
    client = _FakeWorkspaceClient(_FakeSdkObject(_payload()))

    state = observe_databricks_table(
        client=client,
        table_fqn="main.silver.orders",
        source_identifier="https://adb.example",
        captured_at=CAPTURED_AT,
    )

    assert state.assets[0].tags == ()
    assert all(item.tags == () for item in state.assets[0].properties)
    tag_metric = next(
        item
        for item in summarize_observed_evidence(state).by_kind
        if item.kind is ObservedEvidenceKind.TAG
    )
    assert tag_metric.count == 0
    assert tag_metric.availability is ObservedEvidenceAvailabilityStatus.UNAVAILABLE


def test_foreign_key_with_unresolved_parent_preserves_partial_evidence() -> None:
    payload = _payload()
    payload["table_constraints"] = [
        {
            "foreign_key_constraint": {
                "name": "fk_partial",
                "child_columns": ["customer_id"],
                "parent_table": "unqualified-parent",
                "parent_columns": [],
            }
        }
    ]

    state = map_databricks_table_info(
        _FakeSdkObject(payload),
        source_identifier="workspace-a",
        captured_at=CAPTURED_AT,
    )
    relationship = state.assets[0].relationships[0]

    assert relationship.target_asset is None
    assert relationship.target_reference == "unqualified-parent"
    assert relationship.target_properties == ()


def test_mapper_accepts_official_databricks_sdk_table_info_when_extra_is_installed() -> None:
    catalog = pytest.importorskip("databricks.sdk.service.catalog")
    table = catalog.TableInfo.from_dict(_payload())

    state = map_databricks_table_info(
        table,
        source_identifier="https://adb.example",
        captured_at=CAPTURED_AT,
    )

    assert state.assets[0].identity.namespace == ("main", "silver")
    assert state.assets[0].properties[0].identity.property == "order_id"
    assert state.assets[0].owner == "data-platform@example.com"
    assert state.assets[0].relationships[0].name == "fk_orders_customer"
    assert state.fingerprint is not None


def test_observation_models_are_immutable() -> None:
    state = map_databricks_table_info(
        _FakeSdkObject(_payload()),
        source_identifier="https://adb.example",
        captured_at=CAPTURED_AT,
    )

    with pytest.raises(ValidationError):
        state.platform = "other-platform"  # type: ignore[misc]


def test_databricks_observer_does_not_depend_on_contract_projection_layers() -> None:
    source = inspect.getsource(databricks_observation)

    assert "open_data_contract_standard" not in source
    assert "datacontract.imports" not in source
    assert "semapact.importers" not in source
    assert "semapact.lifecycle" not in source
    assert "semapact.governance" not in source


def test_observation_requires_timezone_aware_capture_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        map_databricks_table_info(
            _FakeSdkObject(_payload()),
            source_identifier="https://adb.example",
            captured_at=datetime(2026, 8, 30, 3, 0),
        )
