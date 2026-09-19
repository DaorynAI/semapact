"""Databricks composition factory for read/write platform integrations."""

from __future__ import annotations

from collections.abc import Mapping

from open_data_contract_standard.model import Server

from semapact.deployment.adapters import DeploymentAdapter
from semapact.observation.providers import RuntimeProvider
from semapact.exceptions import ValidationError
from semapact.platforms.databricks.client import create_databricks_workspace_client
from semapact.platforms.databricks.deployment import DatabricksDeploymentAdapter
from semapact.platforms.databricks.runtime import DatabricksRuntimeProvider
from semapact.platforms.factories import PlatformFactory


class DatabricksPlatformFactory(PlatformFactory):
    key = "databricks"

    def runtime_target_from_server(self, server: Server) -> str:
        catalog = _required(
            server.catalog,
            "Databricks contract server must define catalog",
        )
        schema_name = _required(
            server.schema_,
            "Databricks contract server must define schema",
        )
        return f"{catalog}.{schema_name}"

    def create_runtime_provider(
        self,
        *,
        contract_server: Server | None = None,
    ) -> RuntimeProvider:
        client = self._client(contract_server)
        return self._runtime_provider(client)

    def create_deployment_adapter(
        self,
        *,
        contract_server: Server | None = None,
        execution_options: Mapping[str, object] | None = None,
    ) -> DeploymentAdapter:
        options = dict(execution_options or {})
        unsupported = sorted(set(options) - {"warehouse_id"})
        if unsupported:
            raise ValueError(
                f"Unsupported Databricks deployment execution options: {unsupported}"
            )

        warehouse_id = options.get("warehouse_id")
        if warehouse_id is not None and not isinstance(warehouse_id, str):
            raise ValueError("Databricks warehouse_id must be a string")

        client = self._client(contract_server)
        return DatabricksDeploymentAdapter(
            client=client,
            runtime_provider=self._runtime_provider(client),
            warehouse_id=warehouse_id,
        )

    @staticmethod
    def _client(contract_server: Server | None):
        return create_databricks_workspace_client(
            workspace_url=_clean(contract_server.host) if contract_server else None
        )

    @staticmethod
    def _runtime_provider(client) -> DatabricksRuntimeProvider:
        source_identifier = getattr(getattr(client, "config", None), "host", None)
        if not isinstance(source_identifier, str) or not source_identifier.strip():
            raise RuntimeError("Databricks SDK did not resolve a workspace host")
        return DatabricksRuntimeProvider(
            client=client,
            source_identifier=source_identifier,
        )


def _clean(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _required(value: object, message: str) -> str:
    cleaned = _clean(value)
    if not cleaned:
        raise ValidationError(message)
    return cleaned
