"""Runtime-location resolution and provider composition boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from open_data_contract_standard.model import OpenDataContractStandard, Server

from semapact.deployment.adapters import DeploymentAdapter
from semapact.exceptions import ValidationError
from semapact.observation import RuntimeProvider, RuntimeProviderRegistry


@dataclass(frozen=True)
class ResolvedRuntimeLocation:
    """Runtime location resolved from contract metadata or explicit CLI fallback."""

    platform: str
    runtime_target: str
    source: Literal["contract", "cli"]
    server_name: str | None = None
    contract_server: Server | None = None


def resolve_runtime_location(
    contract: OpenDataContractStandard,
    *,
    server_name: str | None = None,
    fallback_platform: str | None = None,
    fallback_runtime_target: str | None = None,
) -> ResolvedRuntimeLocation:
    """Resolve runtime location with contract-first, fail-closed precedence."""
    servers = tuple(contract.servers or ())
    if servers:
        selected = _select_contract_server(servers, server_name)
        platform = _required(selected.type, "Selected contract server must define a runtime type")
        return ResolvedRuntimeLocation(
            platform=platform,
            runtime_target=_runtime_target_from_server(platform, selected),
            source="contract",
            server_name=_required(
                selected.server,
                "Selected contract server must define a server identifier",
            ),
            contract_server=selected,
        )

    if _clean(server_name):
        raise ValidationError(
            "--server cannot be used because the contract defines no servers"
        )

    platform = _clean(fallback_platform)
    runtime_target = _clean(fallback_runtime_target)
    if not platform or not runtime_target:
        raise ValidationError(
            "Contract defines no servers; provide both --platform and --runtime"
        )

    return ResolvedRuntimeLocation(
        platform=platform,
        runtime_target=runtime_target,
        source="cli",
    )


def create_runtime_provider_registry(
    platform: str,
    *,
    contract_server: Server | None = None,
) -> RuntimeProviderRegistry:
    """Create only the selected provider, keeping optional dependencies lazy."""
    normalized = platform.strip().casefold()
    if normalized == "databricks":
        return RuntimeProviderRegistry(
            (_create_databricks_provider(contract_server=contract_server),)
        )
    raise ValidationError(
        f"Unsupported runtime provider '{platform}'. Supported providers: databricks"
    )


def create_deployment_adapter(
    platform: str,
    *,
    warehouse_id: str,
    contract_server: Server | None = None,
) -> DeploymentAdapter:
    """Compose the selected write adapter and provider clients lazily."""
    normalized = platform.strip().casefold()
    if normalized != "databricks":
        raise ValidationError(
            f"Unsupported deployment adapter '{platform}'. Supported adapters: databricks"
        )

    from semapact.platforms.databricks import (
        DatabricksDeploymentAdapter,
        DatabricksRuntimeProvider,
        create_databricks_workspace_client,
    )

    client = create_databricks_workspace_client(
        workspace_url=_clean(contract_server.host) if contract_server else None
    )
    source_identifier = getattr(getattr(client, "config", None), "host", None)
    if not isinstance(source_identifier, str) or not source_identifier.strip():
        raise RuntimeError("Databricks SDK did not resolve a workspace host")
    runtime_provider = DatabricksRuntimeProvider(
        client=client,
        source_identifier=source_identifier,
    )
    return DatabricksDeploymentAdapter(
        client=client,
        runtime_provider=runtime_provider,
        warehouse_id=warehouse_id,
    )


def _select_contract_server(
    servers: tuple[Server, ...],
    requested_name: str | None,
) -> Server:
    requested = _clean(requested_name)
    if requested:
        matches = [
            server
            for server in servers
            if _clean(server.server, casefold=True) == requested.casefold()
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValidationError(
                f"Contract contains duplicate server identifier '{requested}'"
            )
        raise ValidationError(
            f"Contract server '{requested}' was not found. "
            f"Available servers: {_available_server_names(servers)}"
        )

    if len(servers) == 1:
        return servers[0]

    raise ValidationError(
        "Multiple contract servers are defined; select one with --server. "
        f"Available servers: {_available_server_names(servers)}"
    )


def _runtime_target_from_server(platform: str, server: Server) -> str:
    """Project one ODCS server into the selected provider's runtime target."""
    if platform.strip().casefold() == "databricks":
        catalog = _required(server.catalog, "Databricks contract server must define catalog")
        schema = _required(server.schema_, "Databricks contract server must define schema")
        return f"{catalog}.{schema}"
    raise ValidationError(
        f"Unsupported runtime provider '{platform}'. Supported providers: databricks"
    )


def _create_databricks_provider(
    *,
    contract_server: Server | None = None,
) -> RuntimeProvider:
    from semapact.platforms.databricks import (
        DatabricksRuntimeProvider,
        create_databricks_workspace_client,
    )

    client = create_databricks_workspace_client(
        workspace_url=_clean(contract_server.host) if contract_server else None
    )
    source_identifier = getattr(getattr(client, "config", None), "host", None)
    if not isinstance(source_identifier, str) or not source_identifier.strip():
        raise RuntimeError("Databricks SDK did not resolve a workspace host")
    return DatabricksRuntimeProvider(
        client=client,
        source_identifier=source_identifier,
    )


def _available_server_names(servers: tuple[Server, ...]) -> str:
    names = sorted(name for server in servers if (name := _clean(server.server)))
    return ", ".join(names) or "none"


def _required(value: object, message: str) -> str:
    cleaned = _clean(value)
    if not cleaned:
        raise ValidationError(message)
    return cleaned


def _clean(value: object, *, casefold: bool = False) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    return cleaned.casefold() if casefold else cleaned
