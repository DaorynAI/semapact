from __future__ import annotations

import copy
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from semapact.runtime import unity as unity_runtime
from semapact.runtime.models import ObservedContractState, serialize_observed_state
from semapact.runtime.unity import map_unity_table_metadata, observe_unity_table

FIXTURE = Path(__file__).parent / "fixtures" / "runtime" / "unity" / "orders_table_info.json"
CAPTURED_AT = datetime(2026, 8, 30, 3, 0, tzinfo=timezone.utc)


def _payload() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _metadata(entries) -> dict[str, object]:  # noqa: ANN001
    return {item.key: json.loads(item.value_json) for item in entries}


def test_unity_metadata_maps_to_observed_state_without_odcs_projection() -> None:
    payload = _payload()
    original = copy.deepcopy(payload)

    state = map_unity_table_metadata(
        payload,
        source_identifier="https://adb.example/",
        table_fqn="main.silver.orders",
        captured_at=CAPTURED_AT,
    )

    assert isinstance(state, ObservedContractState)
    assert state.platform == "databricks-unity-catalog"
    assert state.source_identifier == "https://adb.example"
    assert state.captured_at == CAPTURED_AT
    assert state.fingerprint is None
    assert payload == original

    assert len(state.assets) == 1
    asset = state.assets[0]
    assert asset.identity.canonical_key == (
        "databricks-unity-catalog",
        "main",
        "silver",
        "orders",
    )
    assert asset.asset_type == "MANAGED"
    assert asset.data_source_format == "DELTA"
    assert asset.owner == "data-platform@example.com"
    assert [(tag.key, tag.value) for tag in asset.tags] == [
        ("domain", "sales"),
        ("tier", "silver"),
    ]

    assert [item.identity.property for item in asset.properties] == [
        "order_id",
        "customer_id",
        "note",
    ]
    order_id = asset.properties[0]
    assert order_id.identity.canonical_key == (
        "databricks-unity-catalog",
        "main",
        "silver",
        "orders",
        "order_id",
    )
    assert order_id.physical_type == "bigint"
    assert order_id.nullable is False
    assert order_id.required is True
    assert _metadata(order_id.metadata)["type_json"] == '{"type":"long"}'

    assert len(asset.constraints) == 1
    assert asset.constraints[0].constraint_type == "PRIMARY_KEY"
    assert asset.constraints[0].name == "pk_orders"
    assert asset.constraints[0].columns == ("order_id",)
    assert _metadata(asset.constraints[0].metadata)["rely"] is True

    assert len(asset.relationships) == 1
    relationship = asset.relationships[0]
    assert relationship.relationship_type == "FOREIGN_KEY"
    assert relationship.source_columns == ("customer_id",)
    assert relationship.target_reference == "main.silver.customers"
    assert relationship.target_columns == ("customer_id",)
    assert relationship.constraint_name == "fk_orders_customer"

    runtime_metadata = _metadata(asset.metadata)
    assert runtime_metadata["table_id"] == "5d3dc5ba-9070-4f24-b21f-4a153fe2a31d"
    assert runtime_metadata["storage_location"].endswith("/orders")
    assert runtime_metadata["properties"]["delta.enableChangeDataFeed"] == "true"
    assert runtime_metadata["runtime_extension"] == {
        "revision": 7,
        "source": "fixture",
    }

    assert [(item.kind, item.reference) for item in state.evidence] == [
        ("view_function_dependency", "main.shared.normalize_order"),
        ("view_table_dependency", "main.bronze.orders_raw"),
    ]


def test_observed_state_serialization_is_stable_when_upstream_order_changes() -> None:
    payload = _payload()
    reordered = dict(reversed(list(payload.items())))
    reordered["columns"] = list(reversed(payload["columns"]))  # type: ignore[index]
    reordered["table_constraints"] = list(
        reversed(payload["table_constraints"])  # type: ignore[index]
    )
    dependencies = payload["view_dependencies"]  # type: ignore[index]
    assert isinstance(dependencies, dict)
    reordered["view_dependencies"] = {
        "dependencies": list(reversed(dependencies["dependencies"]))
    }

    left = map_unity_table_metadata(
        payload,
        source_identifier="https://adb.example",
        captured_at=CAPTURED_AT,
    )
    right = map_unity_table_metadata(
        reordered,
        source_identifier="https://adb.example",
        captured_at=CAPTURED_AT,
    )

    assert left == right
    assert serialize_observed_state(left) == serialize_observed_state(right)


def test_observe_unity_table_uses_runtime_fetcher_and_requires_no_live_workspace() -> None:
    calls: list[tuple[str, str, str]] = []

    def fake_fetcher(
        workspace_url: str, token: str, table_fqn: str
    ) -> dict[str, object]:
        calls.append((workspace_url, token, table_fqn))
        return _payload()

    state = observe_unity_table(
        table_fqn="main.silver.orders",
        workspace_url="https://adb.example/",
        token="test-token",
        captured_at=CAPTURED_AT,
        fetcher=fake_fetcher,
    )

    assert calls == [
        ("https://adb.example/", "test-token", "main.silver.orders")
    ]
    assert state.assets[0].identity.asset == "orders"
    assert state.fingerprint is None


def test_observation_models_are_immutable() -> None:
    state = map_unity_table_metadata(
        _payload(),
        source_identifier="https://adb.example",
        captured_at=CAPTURED_AT,
    )

    with pytest.raises(ValidationError):
        state.platform = "other-platform"  # type: ignore[misc]


def test_runtime_observer_has_no_contract_or_governance_layer_dependency() -> None:
    source = inspect.getsource(unity_runtime)

    assert "open_data_contract_standard" not in source
    assert "datacontract" not in source
    assert "semapact.importers" not in source
    assert "semapact.lifecycle" not in source
    assert "semapact.governance" not in source


def test_observation_requires_timezone_aware_capture_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        map_unity_table_metadata(
            _payload(),
            source_identifier="https://adb.example",
            captured_at=datetime(2026, 8, 30, 3, 0),
        )
