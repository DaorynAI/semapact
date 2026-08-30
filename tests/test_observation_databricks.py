from __future__ import annotations

import inspect
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from semapact.observation import databricks as databricks_observation
from semapact.observation.databricks import (
    map_databricks_table_info,
    observe_databricks_table,
)
from semapact.observation.models import ObservedPlatformState, serialize_observed_state

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


class _FakeTableInfo:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def as_dict(self) -> dict[str, object]:
        return self._payload


class _FakeTablesApi:
    def __init__(self, table: _FakeTableInfo) -> None:
        self._table = table
        self.calls: list[str] = []

    def get(self, full_name: str) -> _FakeTableInfo:
        self.calls.append(full_name)
        return self._table


class _FakeWorkspaceClient:
    def __init__(self, table: _FakeTableInfo) -> None:
        self.tables = _FakeTablesApi(table)


def test_databricks_table_info_maps_to_platform_neutral_observation() -> None:
    state = map_databricks_table_info(
        _FakeTableInfo(_payload()),
        source_identifier="https://adb.example/",
        captured_at=CAPTURED_AT,
    )

    assert isinstance(state, ObservedPlatformState)
    assert state.platform == "databricks"
    assert state.source_identifier == "https://adb.example"
    assert state.captured_at == CAPTURED_AT
    assert state.fingerprint is None

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

    assert [item.identity.property for item in asset.properties] == [
        "order_id",
        "customer_id",
        "note",
    ]
    assert asset.properties[0].physical_type == "bigint"
    assert asset.properties[0].nullable is False
    assert asset.properties[1].physical_type == "string"
    assert asset.properties[2].nullable is True


def test_observation_model_identity_does_not_encode_databricks_namespace_names() -> None:
    state = map_databricks_table_info(
        _FakeTableInfo(_payload()),
        source_identifier="workspace-a",
        captured_at=CAPTURED_AT,
    )

    identity_fields = set(state.assets[0].identity.model_fields)
    assert identity_fields == {"platform", "namespace", "asset"}
    assert "catalog" not in identity_fields
    assert "schema" not in identity_fields


def test_serialization_is_stable_when_databricks_column_order_changes() -> None:
    payload = _payload()
    reordered = dict(payload)
    reordered["columns"] = list(reversed(payload["columns"]))  # type: ignore[index]

    left = map_databricks_table_info(
        _FakeTableInfo(payload),
        source_identifier="https://adb.example",
        captured_at=CAPTURED_AT,
    )
    right = map_databricks_table_info(
        _FakeTableInfo(reordered),
        source_identifier="https://adb.example",
        captured_at=CAPTURED_AT,
    )

    assert left == right
    assert serialize_observed_state(left) == serialize_observed_state(right)


def test_observe_databricks_table_uses_workspace_client_tables_get() -> None:
    client = _FakeWorkspaceClient(_FakeTableInfo(_payload()))

    state = observe_databricks_table(
        client=client,
        table_fqn="main.silver.orders",
        source_identifier="https://adb.example",
        captured_at=CAPTURED_AT,
    )

    assert client.tables.calls == ["main.silver.orders"]
    assert state.assets[0].identity.asset == "orders"


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


def test_observation_models_are_immutable() -> None:
    state = map_databricks_table_info(
        _FakeTableInfo(_payload()),
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
            _FakeTableInfo(_payload()),
            source_identifier="https://adb.example",
            captured_at=datetime(2026, 8, 30, 3, 0),
        )
