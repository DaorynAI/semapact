"""Composition root for runtime provider implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.exceptions import ValidationError
from semapact.observation import RuntimeProvider, RuntimeProviderRegistry


@dataclass(frozen=True)
class ResolvedRuntimeLocation:
    """Runtime location resolved from contract metadata or explicit CLI fallback."""

    platform: str
    runtime_target: str
    source: Literal["contract", "cli"]
    server_name: str | None = None
    contract_server: object | None = None


def resolve_runtime_location(
    contract: OpenDataContractStandard,
    *,
    server_name: str | None = None,
    fallback_platform: str | None = None,
    fallback_runtime_target: str | None = None,
) -> ResolvedRuntimeLocation:
    """Resolve runtime metadata with contract-first, fail-closed precedence.

    Contract ``servers`` are authoritative when present. CLI platform/runtime values
    are fallback only and are consulted exclusively when the contract defines no
    servers.
    """
    servers = tuple(getattr(contract, "servers", None) or ())
    if servers:
        selected = _select_contract_server(servers, server_name)
        platform = _required_text(
            getattr(selected, "type", None),
            "Selected contract server must define a runtime type",
        )
        resolved_name = _required_text(
            getattr(selected, "server", None),
            "Selected contract server must define a server identifier",
        )
        return ResolvedRuntimeLocation(
            platform=platform,
            runtime_target=_runtime_target_from_contract_server(platform, selected),
            source="contract",
            server_name=resolved_name,
            contract_server=selected,
        )

    if _clean_optional(server_name):
        raise ValidationError(
            "--server cannot be used because the contract defines no servers"
        )

    platform = _clean_optional(fallback_platform)
    runtime_target = _clean_optional(fallback_runtime_target)
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
    contract_server: object | None = None,
) -> RuntimeProviderRegistry:
    """Create a registry containing the selected supported runtime provider.

    Provider construction remains outside reconciliation and CLI semantics. Only the
    selected provider is initialized so unrelated optional dependencies or credentials
    are never required.
    """
    normalized = platform.strip().casefold()
    if normalized == "databricks":
        return RuntimeProviderRegistry(
            (_create_databricks_provider(contract_server=contract_server),)
        )
    raise ValidationError(
        f"Unsupported runtime provider '{platform}'. Supported providers: databricks"
    )


def _select_contract_server(
    servers: tuple[object, ...],
    requested_name: str | None,
) -> object:
    requested = _clean_optional(requested_name)
    if requested:
        matches = [
            server
            for server in servers
            if _optional_text(getattr(server, "server", None), casefold=True)
            == requested.casefold()
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValidationError(
                f"Contract contains duplicate server identifier '{requested}'"
            )
        available = ", ".join(sorted(_server_names(servers))) or "none"
        raise ValidationError(
            f"Contract server '{requested}' was not found. Available servers: {available}"
        )

    if len(servers) == 1:
        return servers[0]

    available = ", ".join(sorted(_server_names(servers))) or "none"
    raise ValidationError(
        "Multiple contract servers are defined; select one with --server. "
        f"Available servers: {available}"
    )


def _runtime_target_from_contract_server(platform: str, server: object) -> str:
    normalized = platform.strip().casefold()
    if normalized == "databricks":
        catalog = _required_text(
            getattr(server, "catalog", None),
            "Databricks contract server must define catalog",
        )
        schema = _required_text(
            getattr(server, "schema", None),
            "Databricks contract server must define schema",
        )
        return f"{catalog}.{schema}"
    raise ValidationError(
        f"Unsupported runtime provider '{platform}'. Supported providers: databricks"
    )


def _create_databricks_provider(
    *,
    contract_server: object | None = None,
) -> RuntimeProvider:
    from semapact.platforms.databricks import (
        DatabricksRuntimeProvider,
        create_databricks_workspace_client,
    )

    workspace_url = (
        _clean_optional(getattr(contract_server, "host", None))
        if contract_server is not None
        else None
    )
    client = create_databricks_workspace_client(workspace_url=workspace_url)
    config = getattr(client, "config", None)
    source_identifier = getattr(config, "host", None)
    if not isinstance(source_identifier, str) or not source_identifier.strip():
        raise RuntimeError("Databricks SDK did not resolve a workspace host")
    return DatabricksRuntimeProvider(
        client=client,
        source_identifier=source_identifier,
    )


def _server_names(servers: tuple[object, ...]) -> tuple[str, ...]:
    names = []
    for server in servers:
        name = _optional_text(getattr(server, "server", None))
        if name:
            names.append(name)
    return tuple(names)


def _required_text(value: object, message: str) -> str:
    cleaned = _clean_optional(value)
    if not cleaned:
        raise ValidationError(message)
    return cleaned


def _optional_text(value: object, *, casefold: bool = False) -> str | None:
    cleaned = _clean_optional(value)
    if cleaned is None:
        return None
    return cleaned.casefold() if casefold else cleaned


def _clean_optional(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None
