"""Secret-safe read-only readiness checks for Databricks deployment."""

from __future__ import annotations

import time
from typing import Any

from semapact.application.models.readiness import ReadinessCheck, ReadinessStatus
from semapact.platforms.databricks.configuration import (
    create_configured_databricks_workspace_client,
)


_TERMINAL_STATES = {"SUCCEEDED", "FAILED", "CANCELED", "CLOSED"}


class DatabricksReadinessProbe:
    """Check the exact prerequisites used by SemaPact's Databricks deployment path."""

    key = "databricks"

    def __init__(
        self,
        *,
        runtime_target: str,
        workspace_url: str | None = None,
        warehouse_id: str | None = None,
        poll_interval_seconds: float = 0.2,
        max_poll_attempts: int = 10,
    ) -> None:
        self._runtime_target = runtime_target.strip()
        self._workspace_url = _clean(workspace_url)
        self._warehouse_id = _clean(warehouse_id)
        self._poll_interval_seconds = poll_interval_seconds
        self._max_poll_attempts = max_poll_attempts

    def run(self) -> tuple[ReadinessCheck, ...]:
        try:
            client = create_configured_databricks_workspace_client(
                workspace_url=self._workspace_url,
            )
        except Exception as exc:
            return (
                _failure(
                    "databricks.configuration",
                    "Databricks SDK client could not be initialized.",
                    exc,
                    remediation='Install the Databricks extra and configure Databricks unified authentication.',
                ),
                _skipped(
                    "databricks.identity",
                    "Workspace identity was not checked because client initialization failed.",
                ),
                _skipped(
                    "databricks.unity_catalog",
                    "Unity Catalog access was not checked because client initialization failed.",
                ),
                _skipped(
                    "databricks.statement_execution",
                    "Statement Execution access was not checked because client initialization failed.",
                ),
            )

        host = getattr(getattr(client, "config", None), "host", None)
        if not isinstance(host, str) or not host.strip():
            return (
                ReadinessCheck(
                    check_id="databricks.configuration",
                    status=ReadinessStatus.FAIL,
                    required=True,
                    summary="Databricks SDK did not resolve a workspace host.",
                    remediation="Configure a workspace host through the contract server or Databricks unified authentication.",
                ),
                _skipped(
                    "databricks.identity",
                    "Workspace identity was not checked because no workspace host was resolved.",
                ),
                _skipped(
                    "databricks.unity_catalog",
                    "Unity Catalog access was not checked because no workspace host was resolved.",
                ),
                _skipped(
                    "databricks.statement_execution",
                    "Statement Execution access was not checked because no workspace host was resolved.",
                ),
            )

        checks = [
            ReadinessCheck(
                check_id="databricks.configuration",
                status=ReadinessStatus.PASS,
                required=True,
                summary="Databricks SDK resolved workspace configuration.",
            ),
            self._check_identity(client),
            self._check_unity_catalog(client),
            self._check_statement_execution(client),
        ]
        return tuple(checks)

    def _check_identity(self, client: Any) -> ReadinessCheck:
        try:
            client.current_user.me()
        except Exception as exc:
            return _failure(
                "databricks.identity",
                "Current Databricks identity could not be resolved.",
                exc,
                remediation="Verify workspace connectivity and the configured Databricks credentials.",
            )
        return ReadinessCheck(
            check_id="databricks.identity",
            status=ReadinessStatus.PASS,
            required=True,
            summary="Databricks workspace identity is authenticated.",
        )

    def _check_unity_catalog(self, client: Any) -> ReadinessCheck:
        try:
            client.schemas.get(full_name=self._runtime_target)
        except Exception as exc:
            return _failure(
                "databricks.unity_catalog",
                "Target Unity Catalog schema is not readable by the current identity.",
                exc,
                remediation="Grant the deployment identity metadata access to the governed catalog and schema.",
            )
        return ReadinessCheck(
            check_id="databricks.unity_catalog",
            status=ReadinessStatus.PASS,
            required=True,
            summary="Target Unity Catalog schema is readable.",
        )

    def _check_statement_execution(self, client: Any) -> ReadinessCheck:
        if self._warehouse_id is None:
            return ReadinessCheck(
                check_id="databricks.statement_execution",
                status=ReadinessStatus.FAIL,
                required=True,
                summary="No Databricks SQL warehouse was configured for deployment execution.",
                remediation="Provide --warehouse-id for the SQL warehouse used by governed deployment mutations.",
            )

        try:
            response = client.statement_execution.execute_statement(
                statement="SELECT 1",
                warehouse_id=self._warehouse_id,
                wait_timeout="10s",
            )
            state = _statement_state(response)
            attempts = 0
            while state not in _TERMINAL_STATES and attempts < self._max_poll_attempts:
                statement_id = getattr(response, "statement_id", None)
                if not statement_id:
                    raise RuntimeError(
                        "Databricks readiness statement returned no statement_id"
                    )
                if self._poll_interval_seconds:
                    time.sleep(self._poll_interval_seconds)
                response = client.statement_execution.get_statement(statement_id)
                state = _statement_state(response)
                attempts += 1

            if state != "SUCCEEDED":
                raise RuntimeError(
                    "Databricks readiness statement did not complete successfully"
                )
        except Exception as exc:
            return _failure(
                "databricks.statement_execution",
                "Databricks Statement Execution is not usable with the configured warehouse.",
                exc,
                remediation="Verify warehouse availability and CAN USE / statement-execution permissions for the deployment identity.",
            )

        return ReadinessCheck(
            check_id="databricks.statement_execution",
            status=ReadinessStatus.PASS,
            required=True,
            summary="Read-only Statement Execution succeeded on the configured SQL warehouse.",
        )


def _failure(
    check_id: str,
    summary: str,
    exc: Exception,
    *,
    remediation: str,
) -> ReadinessCheck:
    return ReadinessCheck(
        check_id=check_id,
        status=ReadinessStatus.FAIL,
        required=True,
        summary=summary,
        remediation=remediation,
        error_type=type(exc).__name__,
    )


def _skipped(check_id: str, summary: str) -> ReadinessCheck:
    return ReadinessCheck(
        check_id=check_id,
        status=ReadinessStatus.SKIP,
        required=True,
        summary=summary,
    )


def _statement_state(response: Any) -> str:
    status = getattr(response, "status", None)
    state = getattr(status, "state", None)
    if state is None:
        raise RuntimeError("Databricks statement response did not contain status.state")
    value = getattr(state, "value", state)
    return str(value).upper()


def _clean(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None
