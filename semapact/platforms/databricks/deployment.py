"""Databricks deployment wiring and Statement Execution API executor."""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import field_validator

from semapact.deployment import RuntimeReleaseMetadata
from semapact.deployment.models import (
    DeploymentPlan,
    NativeOperation,
    NativeOperationKind,
)
from semapact.deployment.orchestrator import DeploymentOrchestrator
from semapact.deployment.providers import (
    DeploymentExecutionConfig,
    NativeOperationExecutor,
)
from semapact.exceptions import ValidationError
from semapact.observation.providers import RuntimeProvider
from semapact.platforms.databricks.transition_compiler import (
    DatabricksTransitionCompiler,
)
from semapact.platforms.databricks.target import parse_databricks_runtime_target
from semapact.platforms.databricks.transition_planner import (
    DatabricksSchemaTransitionPlanner,
)
from semapact.schema import SqlSchemaMapper, validate_simple_sql_identifier


_TERMINAL_STATES = {"SUCCEEDED", "FAILED", "CANCELED", "CLOSED"}



class DatabricksDeploymentExecutionConfig(DeploymentExecutionConfig):
    """Typed Databricks execution configuration."""

    platform: Literal["databricks"] = "databricks"
    warehouse_id: str | None = None

    @field_validator("warehouse_id")
    @classmethod
    def _normalize_warehouse_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class DatabricksStatementExecutor(NativeOperationExecutor):
    """Execute exact native operations through Databricks Statement Execution API."""

    key = "databricks"

    def __init__(
        self,
        *,
        client: Any,
        warehouse_id: str | None = None,
        poll_interval_seconds: float = 1.0,
        max_poll_attempts: int = 300,
    ) -> None:
        if poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds must be non-negative")
        if max_poll_attempts < 1:
            raise ValueError("max_poll_attempts must be positive")

        self._client = client
        self._warehouse_id = (
            warehouse_id.strip()
            if warehouse_id and warehouse_id.strip()
            else None
        )
        self._poll_interval_seconds = poll_interval_seconds
        self._max_poll_attempts = max_poll_attempts

    def execute(self, operation: NativeOperation) -> None:
        """Execute one exact compiled operation using the Databricks SDK API."""
        statement = operation.statement
        if statement is None or not statement.strip():
            raise ValidationError(
                "Databricks executable operation requires a SQL statement"
            )
        self._run_statement(statement)

    def query_rows(self, statement: str) -> tuple[tuple[str | None, ...], ...]:
        """Execute one small metadata query and return its inline JSON rows."""
        response = self._run_statement(statement)
        result = getattr(response, "result", None)
        data_array = getattr(result, "data_array", None) if result is not None else None
        if not data_array:
            return ()
        return tuple(tuple(value for value in row) for row in data_array)

    def _run_statement(self, statement: str) -> Any:
        if self._warehouse_id is None:
            raise ValidationError(
                "Databricks deployment execution requires a SQL warehouse_id"
            )

        response = self._client.statement_execution.execute_statement(
            statement=statement,
            warehouse_id=self._warehouse_id,
            wait_timeout="10s",
        )
        state = _statement_state(response)
        attempts = 0

        while state not in _TERMINAL_STATES:
            statement_id = getattr(response, "statement_id", None)
            if not statement_id:
                raise RuntimeError(
                    "Databricks statement is non-terminal but returned no statement_id"
                )
            if attempts >= self._max_poll_attempts:
                raise RuntimeError(
                    f"Databricks statement did not reach terminal state: {statement_id}"
                )

            if self._poll_interval_seconds:
                time.sleep(self._poll_interval_seconds)

            response = self._client.statement_execution.get_statement(statement_id)
            state = _statement_state(response)
            attempts += 1

        if state != "SUCCEEDED":
            status = getattr(response, "status", None)
            error = getattr(status, "error", None)
            raise RuntimeError(
                f"Databricks deployment statement finished with state {state}: {error}"
            )
        return response


class DatabricksDeploymentAdapter(DeploymentOrchestrator):
    """Databricks wiring over the generic deployment orchestrator."""

    def __init__(
        self,
        *,
        client: Any,
        runtime_provider: RuntimeProvider,
        warehouse_id: str | None = None,
        poll_interval_seconds: float = 1.0,
        max_poll_attempts: int = 300,
    ) -> None:
        statement_executor = DatabricksStatementExecutor(
            client=client,
            warehouse_id=warehouse_id,
            poll_interval_seconds=poll_interval_seconds,
            max_poll_attempts=max_poll_attempts,
        )
        self._statement_executor = statement_executor
        super().__init__(
            runtime_provider=runtime_provider,
            schema_mapper=SqlSchemaMapper(
                key="databricks",
                server_type="databricks",
                dialect="databricks",
            ),
            transition_planner=DatabricksSchemaTransitionPlanner(),
            transition_compiler=DatabricksTransitionCompiler(),
            executor=statement_executor,
        )


    def project_release_metadata(
        self,
        plan: DeploymentPlan,
        metadata: RuntimeReleaseMetadata,
    ) -> None:
        """Project SemaPact release provenance into Unity Catalog table tags."""
        if metadata.contract_id != plan.contract_id:
            raise ValidationError(
                "Release metadata contract does not match DeploymentPlan"
            )
        if metadata.contract_version != plan.contract_version:
            raise ValidationError(
                "Release metadata version does not match DeploymentPlan"
            )

        catalog, schema_name = parse_databricks_runtime_target(
            plan.target.runtime_target
        )
        validate_simple_sql_identifier(catalog, "catalog")
        validate_simple_sql_identifier(schema_name, "schema")

        tags = {
            "semapact_contract_id": metadata.contract_id,
            "semapact_contract_version": metadata.contract_version,
            "semapact_release_id": metadata.contract_release_id,
            "semapact_source_revision": metadata.source_revision_ref,
        }
        rendered_tags = ", ".join(
            f"{_sql_string(key)} = {_sql_string(value)}"
            for key, value in sorted(tags.items())
        )
        rendered_keys = ", ".join(_sql_string(key) for key in sorted(tags))
        for action in plan.actions:
            validate_simple_sql_identifier(action.physical_name, "asset")
            qualified = ".".join(
                f"`{part}`"
                for part in (catalog, schema_name, action.physical_name)
            )
            current_tags = self._read_release_tags(
                catalog=catalog,
                schema_name=schema_name,
                table_name=action.physical_name,
                reserved_keys=tuple(sorted(tags)),
            )
            if current_tags == tags:
                continue
            if current_tags:
                self._statement_executor.execute(
                    NativeOperation(
                        kind=NativeOperationKind.ALTER,
                        governed_asset=action.governed_asset,
                        statement=(
                            f"ALTER TABLE {qualified} UNSET TAGS ({rendered_keys})"
                        ),
                    )
                )
            self._statement_executor.execute(
                NativeOperation(
                    kind=NativeOperationKind.ALTER,
                    governed_asset=action.governed_asset,
                    statement=(
                        f"ALTER TABLE {qualified} SET TAGS ({rendered_tags})"
                    ),
                )
            )

    def _read_release_tags(
        self,
        *,
        catalog: str,
        schema_name: str,
        table_name: str,
        reserved_keys: tuple[str, ...],
    ) -> dict[str, str]:
        keys = ", ".join(_sql_string(key) for key in reserved_keys)
        statement = (
            "SELECT tag_name, tag_value "
            f"FROM `{catalog}`.information_schema.table_tags "
            f"WHERE schema_name = {_sql_string(schema_name)} "
            f"AND table_name = {_sql_string(table_name)} "
            f"AND tag_name IN ({keys})"
        )
        current: dict[str, str] = {}
        for row in self._statement_executor.query_rows(statement):
            if len(row) != 2 or row[0] is None or row[1] is None:
                raise RuntimeError(
                    "Databricks table tag query returned an invalid row"
                )
            key, value = row
            if key in current:
                raise RuntimeError(
                    f"Databricks table tag query returned duplicate key: {key}"
                )
            current[key] = value
        return current


def _statement_state(response: Any) -> str:
    status = getattr(response, "status", None)
    state = getattr(status, "state", None)
    if state is None:
        raise RuntimeError(
            "Databricks statement response did not contain status.state"
        )
    value = getattr(state, "value", state)
    return str(value).upper()


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
