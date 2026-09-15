from __future__ import annotations

import inspect
from datetime import datetime, timezone
from types import SimpleNamespace

from semapact.observation import (
    ObservedEvidenceAvailabilityStatus,
    ObservedLineageEvidenceType,
    serialize_observed_lineage_result,
)
from semapact.platforms.databricks import lineage as databricks_lineage
from semapact.platforms.databricks.lineage import observe_databricks_lineage

CAPTURED_AT = datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc)


class _FakeCursor:
    def __init__(self, *, reverse: bool = False, fail: set[str] | None = None) -> None:
        self.reverse = reverse
        self.fail = fail or set()
        self._rows = []
        self.queries: list[str] = []

    def execute(self, query: str, parameters: tuple[str, ...] | None = None) -> None:
        self.queries.append(query)
        if "system.access.column_lineage" in query:
            kind = "column"
            rows = [
                SimpleNamespace(
                    source_table_full_name="main.raw.orders",
                    source_column_name="raw_id",
                    target_table_full_name="main.silver.orders",
                    target_column_name="order_id",
                    statement_id="stmt-1",
                    event_time=CAPTURED_AT,
                    event_id="event-1",
                    record_id="column-record-1",
                    created_by="pipeline@example.com",
                    direct_access=True,
                ),
                SimpleNamespace(
                    source_table_full_name="main.raw.orders",
                    source_column_name="raw_customer_id",
                    target_table_full_name="main.silver.orders",
                    target_column_name="customer_id",
                    statement_id="stmt-1",
                    event_time=CAPTURED_AT,
                    event_id="event-1",
                    record_id="column-record-2",
                    created_by="pipeline@example.com",
                    direct_access=True,
                ),
            ]
        elif "system.query.history" in query:
            kind = "query"
            rows = [
                SimpleNamespace(
                    source_table_full_name="main.raw.orders",
                    target_table_full_name="main.silver.orders",
                    statement_id="stmt-1",
                    event_time=CAPTURED_AT,
                    event_id="event-1",
                    record_id="table-record-1",
                    created_by="pipeline@example.com",
                    direct_access=True,
                    statement_text="INSERT INTO main.silver.orders SELECT * FROM main.raw.orders",
                    statement_type="INSERT",
                )
            ]
        else:
            kind = "table"
            rows = [
                SimpleNamespace(
                    source_table_full_name="main.raw.orders",
                    target_table_full_name="main.silver.orders",
                    statement_id="stmt-1",
                    event_time=CAPTURED_AT,
                    event_id="event-1",
                    record_id="table-record-1",
                    created_by="pipeline@example.com",
                    direct_access=True,
                )
            ]
        if kind in self.fail:
            raise PermissionError(f"no access to {kind}")
        self._rows = list(reversed(rows)) if self.reverse else rows

    def fetchall(self):
        return self._rows


def _availability(result):
    return {item.evidence_type: item.status for item in result.availability}


def test_databricks_lineage_is_normalized_without_odcs_mutation() -> None:
    cursor = _FakeCursor()

    result = observe_databricks_lineage(
        cursor=cursor,
        table_fqn="main.silver.orders",
        source_identifier="https://adb.example/",
        captured_at=CAPTURED_AT,
    )

    assert result.platform == "databricks"
    assert result.source_identifier == "https://adb.example"
    assert result.target_reference == "main.silver.orders"
    assert {item.evidence_type for item in result.evidence} == {
        ObservedLineageEvidenceType.TABLE,
        ObservedLineageEvidenceType.COLUMN,
        ObservedLineageEvidenceType.QUERY,
    }

    columns = [
        item
        for item in result.evidence
        if item.evidence_type is ObservedLineageEvidenceType.COLUMN
    ]
    assert [(item.source_property, item.target_property) for item in columns] == [
        ("raw_customer_id", "customer_id"),
        ("raw_id", "order_id"),
    ]
    assert all(item.source_asset is not None for item in columns)
    assert all(item.target_asset is not None for item in columns)

    query = next(
        item
        for item in result.evidence
        if item.evidence_type is ObservedLineageEvidenceType.QUERY
    )
    assert query.statement_reference == "stmt-1"
    assert query.statement_type == "INSERT"
    assert query.statement_text == (
        "INSERT INTO main.silver.orders SELECT * FROM main.raw.orders"
    )
    assert query.capture_context.event_reference == "event-1"
    assert query.capture_context.actor_reference == "pipeline@example.com"

    assert all(
        status is ObservedEvidenceAvailabilityStatus.AVAILABLE
        for status in _availability(result).values()
    )
    assert any("system.query.history" in query for query in cursor.queries)
    assert all("system.access.query_history" not in query for query in cursor.queries)


def test_lineage_order_is_deterministic() -> None:
    first = observe_databricks_lineage(
        cursor=_FakeCursor(),
        table_fqn="main.silver.orders",
        source_identifier="workspace-a",
        captured_at=CAPTURED_AT,
    )
    second = observe_databricks_lineage(
        cursor=_FakeCursor(reverse=True),
        table_fqn="main.silver.orders",
        source_identifier="workspace-a",
        captured_at=CAPTURED_AT,
    )

    assert first == second
    assert serialize_observed_lineage_result(first) == serialize_observed_lineage_result(second)


def test_missing_query_history_permission_preserves_other_lineage() -> None:
    result = observe_databricks_lineage(
        cursor=_FakeCursor(fail={"query"}),
        table_fqn="main.silver.orders",
        source_identifier="workspace-a",
        captured_at=CAPTURED_AT,
    )

    availability = _availability(result)
    assert availability[ObservedLineageEvidenceType.TABLE] is ObservedEvidenceAvailabilityStatus.AVAILABLE
    assert availability[ObservedLineageEvidenceType.COLUMN] is ObservedEvidenceAvailabilityStatus.AVAILABLE
    assert availability[ObservedLineageEvidenceType.QUERY] is ObservedEvidenceAvailabilityStatus.UNAVAILABLE
    assert all(
        item.evidence_type is not ObservedLineageEvidenceType.QUERY
        for item in result.evidence
    )
    assert any(
        item.evidence_type is ObservedLineageEvidenceType.COLUMN
        for item in result.evidence
    )


def test_lineage_adapter_does_not_depend_on_contract_or_governance_layers() -> None:
    source = inspect.getsource(databricks_lineage)

    assert "open_data_contract_standard" not in source
    assert "semapact.importers" not in source
    assert "semapact.lifecycle" not in source
    assert "semapact.governance" not in source
