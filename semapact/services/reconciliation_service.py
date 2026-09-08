"""Application service for provider-neutral runtime product reconciliation."""

from __future__ import annotations

from dataclasses import dataclass

from semapact.core.loader import ContractLoader
from semapact.observation import RuntimeAssetBinding, RuntimeProviderRegistry
from semapact.reconciliation import (
    ReconciliationResult,
    RuntimeDriftStatus,
    classify_reconciliation_status,
    reconcile_governed_contract,
    runtime_asset_specs_from_contract,
)


@dataclass(frozen=True)
class RuntimeReconciliation:
    """One complete read-only reconciliation of a governed data product."""

    platform: str
    runtime_target: str
    bindings: tuple[RuntimeAssetBinding, ...]
    result: ReconciliationResult
    status: RuntimeDriftStatus


class ReconciliationService:
    """Orchestrate load, bind, observe, reconcile, and classify exactly once."""

    def __init__(
        self,
        provider_registry: RuntimeProviderRegistry,
        *,
        contract_loader: ContractLoader | None = None,
    ) -> None:
        self._provider_registry = provider_registry
        self._contract_loader = contract_loader or ContractLoader()

    def reconcile(
        self,
        *,
        contract_path: str,
        platform: str,
        runtime_target: str,
    ) -> RuntimeReconciliation:
        """Reconcile one governed data product against the selected runtime provider."""
        contract = self._contract_loader.load(contract_path)
        provider = self._provider_registry.get(platform)
        asset_specs = runtime_asset_specs_from_contract(contract)
        bindings = provider.resolve_bindings(
            runtime_target=runtime_target,
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
            runtime_target=runtime_target,
            bindings=bindings,
            result=result,
            status=classify_reconciliation_status(result),
        )
