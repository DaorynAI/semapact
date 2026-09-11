"""Application service for provider-neutral runtime product reconciliation."""

from __future__ import annotations

from semapact.application.models.reconciliation import RuntimeReconciliation
from semapact.core.loader import ContractLoader
from semapact.observation import RuntimeProviderRegistry
from semapact.platforms.runtime_registry import (
    create_runtime_provider_registry,
    resolve_runtime_location,
)
from semapact.reconciliation import (
    classify_reconciliation_status,
    reconcile_governed_contract,
    runtime_asset_specs_from_contract,
)


class ReconciliationService:
    """Orchestrate load, runtime resolution, bind, observe, reconcile, and classify."""

    def __init__(
        self,
        provider_registry: RuntimeProviderRegistry | None = None,
        *,
        contract_loader: ContractLoader | None = None,
    ) -> None:
        self._provider_registry = provider_registry
        self._contract_loader = contract_loader or ContractLoader()

    def reconcile(
        self,
        *,
        contract_path: str,
        server_name: str | None = None,
        fallback_platform: str | None = None,
        fallback_runtime_target: str | None = None,
    ) -> RuntimeReconciliation:
        """Reconcile one governed data product against its resolved runtime location."""
        contract = self._contract_loader.load(contract_path)
        location = resolve_runtime_location(
            contract,
            server_name=server_name,
            fallback_platform=fallback_platform,
            fallback_runtime_target=fallback_runtime_target,
        )
        registry = self._provider_registry or create_runtime_provider_registry(
            location.platform,
            contract_server=location.contract_server,
        )
        provider = registry.get(location.platform)
        asset_specs = runtime_asset_specs_from_contract(contract)
        bindings = provider.resolve_bindings(
            runtime_target=location.runtime_target,
            assets=asset_specs,
        )
        observation = provider.observe(bindings=bindings)
        result = reconcile_governed_contract(
            contract,
            observation,
            asset_bindings=bindings,
        )
        return RuntimeReconciliation(
            platform=provider.key,
            runtime_target=location.runtime_target,
            runtime_source=location.source,
            server_name=location.server_name,
            bindings=bindings,
            result=result,
            status=classify_reconciliation_status(result),
        )
