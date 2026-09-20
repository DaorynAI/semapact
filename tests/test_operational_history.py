from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from semapact.history import (
    build_operational_deployment_event,
    create_operational_history_sink,
)
from semapact.platforms.delta import DeltaOperationalHistorySink
from semapact.platforms.sqlite import SQLiteOperationalHistorySink
from semapact.reconciliation import RuntimeDriftStatus


def _event():
    return build_operational_deployment_event(
        bundle_digest="sha256:" + ("a" * 64),
        release=False,
        release_record_id=None,
        contract_id="orders-product",
        contract_version="1.2.3",
        revision_ref="git:abc123",
        deployment_plan_id="plan-1",
        deployment_preview_id="preview-1",
        deployment_authorization_id="auth-1",
        platform="databricks",
        runtime_target="main.sales",
        source_reference="https://workspace.example",
        status="SUCCEEDED",
        reconciliation_status=RuntimeDriftStatus.IN_SYNC,
        started_at=datetime(2026, 9, 20, 1, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 9, 20, 1, 1, tzinfo=timezone.utc),
        error_message=None,
    )


def test_operational_history_is_disabled_when_not_configured() -> None:
    assert create_operational_history_sink(None) is None
    assert create_operational_history_sink("") is None


def test_sqlite_operational_history_is_idempotent(tmp_path) -> None:
    database = tmp_path / "operational.db"
    sink = create_operational_history_sink(f"sqlite:///{database}")

    assert isinstance(sink, SQLiteOperationalHistorySink)
    event = _event()
    sink.record_deployment(event)
    sink.record_deployment(event)

    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT event_id, payload_json FROM deployment_events"
        ).fetchall()

    assert len(rows) == 1
    assert rows[0][0] == event.event_id
    assert json.loads(rows[0][1])["deployment_plan_id"] == "plan-1"


def test_delta_operational_history_adapter_is_lazy() -> None:
    sink = create_operational_history_sink("delta:///tmp/semapact-history")

    assert isinstance(sink, DeltaOperationalHistorySink)
