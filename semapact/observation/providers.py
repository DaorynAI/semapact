"""Platform-neutral runtime product provider contracts."""

from __future__ import annotations

from typing import Protocol, Sequence

from pydantic import BaseModel, ConfigDict

from semapact.observation.models import ObservedAssetIdentity, ObservedPlatformState
from semapact.runtime import RuntimeAssetSpec


class RuntimeProviderModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RuntimeAssetBinding(RuntimeProviderModel):
    """Explicit logical governed asset to provider-local runtime identity binding."""

    governed_asset: str
    observed_asset: ObservedAssetIdentity


class RuntimeProvider(Protocol):
    """Minimal provider seam for runtime product binding and observation."""

    key: str

    def resolve_bindings(
        self,
        *,
        runtime_target: str,
        assets: Sequence[RuntimeAssetSpec],
    ) -> tuple[RuntimeAssetBinding, ...]: ...

    def observe(
        self,
        *,
        bindings: Sequence[RuntimeAssetBinding],
    ) -> ObservedPlatformState: ...


class RuntimeProviderRegistry:
    """Small deterministic provider registry used by application interfaces."""

    def __init__(self, providers: Sequence[RuntimeProvider] = ()) -> None:
        self._providers: dict[str, RuntimeProvider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: RuntimeProvider) -> None:
        key = provider.key.strip().casefold()
        if not key:
            raise ValueError("Runtime provider key is required")
        if key in self._providers:
            raise ValueError(f"Runtime provider already registered: {provider.key}")
        self._providers[key] = provider

    def get(self, key: str) -> RuntimeProvider:
        normalized = key.strip().casefold()
        try:
            return self._providers[normalized]
        except KeyError:
            supported = ", ".join(sorted(self._providers)) or "none"
            raise ValueError(
                f"Unsupported runtime provider '{key}'. Registered providers: {supported}"
            ) from None

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))
