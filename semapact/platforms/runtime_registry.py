"""Runtime-location resolution and platform composition registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from open_data_contract_standard.model import OpenDataContractStandard, Server

from semapact.deployment.adapters import DeploymentAdapter
from semapact.exceptions import ValidationError
from semapact.observation import RuntimeProviderRegistry
from semapact.platforms.factories import PlatformFactory


@dataclass(frozen=True)
class ResolvedRuntimeLocation:
    """Runtime location resolved from contract metadata or explicit CLI fallback."""

    platform: str
    runtime_target: str
    source: Literal["contract", "cli"]
    server_name: str | None = None
    contract_server: Server | None = None


PlatformFactoryLoader = Callable[[], PlatformFactory]


def _load_databricks_factory() -> PlatformFactory:
    from semapact.platforms.databricks.factory import DatabricksPlatformFactory

    return DatabricksPlatformFactory()


_PLATFORM_FACTORY_LOADERS: dict[str, PlatformFactoryLoader] = {
    "databricks": _load_databricks_factory,
}


def get_platform_factory(platform: str) -> PlatformFactory:
    """Resolve one lazily loaded platform composition factory."""
    normalized = platform.strip().casefold()
    loader = _PLATFORM_FACTORY_LOADERS.get(normalized)
    if loader is None:
        supported = ", ".join(sorted(_PLATFORM_FACTORY_LOADERS))
        raise ValidationError(
            f"Unsupported runtime provider '{platform}'. Supported providers: {supported}"
        )

    factory = loader()
    if factory.key.strip().casefold() != normalized:
        raise RuntimeError(
            "Platform factory key does not match registry key: "
            f"{factory.key!r} != {normalized!r}"
        )
    return factory


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
        platform = _required(
            selected.type,
            "Selected contract server must define a runtime type",
        )
        factory = get_platform_factory(platform)
        return ResolvedRuntimeLocation(
            platform=factory.key,
            runtime_target=factory.runtime_target_from_server(selected),
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

    factory = get_platform_factory(platform)
    return ResolvedRuntimeLocation(
        platform=factory.key,
        runtime_target=runtime_target,
        source="cli",
    )


def create_runtime_provider_registry(
    platform: str,
    *,
    contract_server: Server | None = None,
) -> RuntimeProviderRegistry:
    """Create only the selected provider, keeping optional dependencies lazy."""
    factory = get_platform_factory(platform)
    return RuntimeProviderRegistry(
        (factory.create_runtime_provider(contract_server=contract_server),)
    )


def create_deployment_adapter(
    platform: str,
    *,
    warehouse_id: str | None = None,
    contract_server: Server | None = None,
) -> DeploymentAdapter:
    """Compose the selected deployment adapter through one platform factory."""
    factory = get_platform_factory(platform)
    return factory.create_deployment_adapter(
        contract_server=contract_server,
        execution_options={"warehouse_id": warehouse_id},
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
