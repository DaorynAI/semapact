"""Application service boundary for read-only runtime reconciliation workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from semapact.core.loader import ContractLoader, RuntimeContext
from semapact.observation.databricks import observe_databricks_table
from semapact.platforms.databricks.client import create_databricks_workspace_client
from semapact.reconciliation import (
    ReconciliationResult,
    RuntimeDriftStatus,
    classify_reconciliation_status,
    reconcile_governed_contract,
)


@dataclass(frozen=True)
class ReconciliationAnalysis:
    """One read-only governed-desired-vs-runtime reconciliation result."""

    runtime_target: str
    result: ReconciliationResult
    status: RuntimeDriftStatus


class ReconciliationService:
    """Coordinate contract loading, observation, reconciliation, and classification."""

    def reconcile_databricks_table(
        self,
        *,
        contract_path: str,
        table_fqn: str,
        workspace_url: str | None = None,
        token: str | None = None,
        profile: str | None = None,
        runtime_context: RuntimeContext | str | None = "auto",
    ) -> ReconciliationAnalysis:
        """Reconcile one governed contract against one Unity Catalog table."""
        contract = ContractLoader(runtime_context=runtime_context or "auto").load(
            contract_path
        )
        client = create_databricks_workspace_client(
            workspace_url=workspace_url,
            token=token,
            profile=profile,
        )
        observation = observe_databricks_table(
            client=client,
            table_fqn=table_fqn,
            source_identifier=_workspace_source_identifier(client),
        )
        result = reconcile_governed_contract(contract, observation)
        return ReconciliationAnalysis(
            runtime_target=table_fqn,
            result=result,
            status=classify_reconciliation_status(result),
        )


def _workspace_source_identifier(client: Any) -> str:
    """Return the workspace host resolved by the Databricks SDK client."""
    config = getattr(client, "config", None)
    host = getattr(config, "host", None)
    if isinstance(host, str) and host.strip():
        return host.strip().rstrip("/")
    raise RuntimeError("Databricks WorkspaceClient did not resolve a workspace host")
