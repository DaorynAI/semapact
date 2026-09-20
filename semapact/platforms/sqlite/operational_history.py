"""SQLite persistence for optional operational deployment history."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from semapact.history.operational import OperationalDeploymentEvent
from semapact.utils.deterministic import canonical_compact_json


class SQLiteOperationalHistorySink:
    """Persist high-frequency deployment events without touching Git history."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).expanduser().resolve(strict=False)

    def record_deployment(self, event: OperationalDeploymentEvent) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = canonical_compact_json(event.model_dump(mode="json"))
        with sqlite3.connect(self._path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS deployment_events (
                    event_id TEXT PRIMARY KEY,
                    completed_at TEXT NOT NULL,
                    contract_id TEXT NOT NULL,
                    deployment_plan_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    runtime_target TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            existing = connection.execute(
                "SELECT payload_json FROM deployment_events WHERE event_id = ?",
                (event.event_id,),
            ).fetchone()
            if existing is not None:
                if existing[0] != payload:
                    raise RuntimeError(
                        "Operational deployment event identity already exists "
                        "with different content"
                    )
                return
            connection.execute(
                """
                INSERT INTO deployment_events (
                    event_id,
                    completed_at,
                    contract_id,
                    deployment_plan_id,
                    platform,
                    runtime_target,
                    status,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.completed_at.isoformat(),
                    event.contract_id,
                    event.deployment_plan_id,
                    event.platform,
                    event.runtime_target,
                    event.status,
                    payload,
                ),
            )
