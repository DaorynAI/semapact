"""Delta Lake persistence for optional operational deployment history."""

from __future__ import annotations

from semapact.history.operational import OperationalDeploymentEvent
from semapact.utils.deterministic import canonical_compact_json


class DeltaOperationalHistorySink:
    """Append deployment telemetry to a Delta table.

    Consumers should use event_id as the idempotency/deduplication key when pipeline
    retry semantics can append the same immutable event more than once.
    """

    def __init__(self, table_uri: str) -> None:
        cleaned = table_uri.strip()
        if not cleaned:
            raise ValueError("Delta operational history table URI is required")
        self._table_uri = cleaned

    def record_deployment(self, event: OperationalDeploymentEvent) -> None:
        try:
            import pyarrow as pa
            from deltalake import write_deltalake
        except ImportError as exc:
            raise RuntimeError(
                'Delta operational history requires: pip install "semapact[delta]"'
            ) from exc

        payload = canonical_compact_json(event.model_dump(mode="json"))
        table = pa.table(
            {
                "event_id": [event.event_id],
                "completed_at": [event.completed_at.isoformat()],
                "contract_id": [event.contract_id],
                "deployment_plan_id": [event.deployment_plan_id],
                "platform": [event.platform],
                "runtime_target": [event.runtime_target],
                "status": [event.status],
                "payload_json": [payload],
            }
        )
        write_deltalake(
            self._table_uri,
            table,
            mode="append",
        )
