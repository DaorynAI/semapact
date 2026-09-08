from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence, cast

from open_data_contract_standard.model import OpenDataContractStandard, SchemaObject, Server

from semapact.core.loader import ContractLoader
from semapact.observation import (
    ObservedAsset,
    ObservedAssetIdentity,
    ObservedPlatformState,
    RuntimeAssetBinding,
    RuntimeAssetSpec,
    RuntimeProviderRegistry,
    with_observed_state_fingerprint,
)
from semapact.reconciliation import RuntimeDriftStatus
from semapact.services.reconciliation_service import ReconciliationService


class _Loader:
    def __init__(self, contract: OpenDataContractStandard) -> None:
        self.contract = contract
        self.loaded_path: str | None = None

    def load(self, contract_path: str) -> OpenDataContractStandard:
        self.loaded_path = contract_path
        return self.contract


class _Provider:
    def __init__(self, key: str) -> None:
        self.key = key
        self.runtime_target: str | None = None
        self.specs: tuple[RuntimeAssetSpec, ...] = ()
        self.observed_bindings: tuple[RuntimeAssetBinding, ...] = ()

    def resolve_bindings(
        self,
        *,
        runtime_target: str,
        assets: Sequence[RuntimeAssetSpec],
    ) -> tuple[RuntimeAssetBinding, ...]:
        self.runtime_target = runtime_target
        self.specs = tuple(assets)
        return (
            RuntimeAssetBinding(
                governed_asset="orders",
                observed_asset=ObservedAssetIdentity(
                    platform=self.key,
                    namespace=("analytics",),
                    asset="fact_orders_v2",
                ),
            ),
        )

    def observe(
        self,
        *,
        bindings: Sequence[RuntimeAssetBinding],
    ) -> ObservedPlatformState:
        self.observed_bindings = tuple(bindings)
        identity = bindings[0].observed_asset
        state = ObservedPlatformState(
            platform=self.key,
            source_identifier=f"{self.key}://test",
            assets=(ObservedAsset(identity=identity, properties=()),),
            captured_at=datetime(2026, 9, 8, 21, 0, tzinfo=timezone.utc),
            fingerprint=None,
        )
        return with_observed_state_fingerprint(state)


def _contract(*, servers: list[Server] | None = None) -> OpenDataContractStandard:
    return OpenDataContractStandard.model_construct(
        id="sales-product",
        version="1.0.0",
        servers=servers,
        schema_=[
            SchemaObject.model_construct(
                name="orders",
                physicalName="fact_orders_v2",
                properties=[],
            )
        ],
    )


def test_reconciliation_service_uses_cli_runtime_only_when_contract_has_no_server() -> None:
    loader = _Loader(_contract())
    provider = _Provider("warehouse")
    service = ReconciliationService(
        RuntimeProviderRegistry((provider,)),
        contract_loader=cast(ContractLoader, loader),
    )

    analysis = service.reconcile(
        contract_path="contracts/sales.yaml",
        fallback_platform="WAREHOUSE",
        fallback_runtime_target="analytics",
    )

    assert loader.loaded_path == "contracts/sales.yaml"
    assert provider.runtime_target == "analytics"
    assert provider.specs == (
        RuntimeAssetSpec(governed_asset="orders", physical_name="fact_orders_v2"),
    )
    assert provider.observed_bindings == analysis.bindings
    assert analysis.platform == "warehouse"
    assert analysis.runtime_target == "analytics"
    assert analysis.runtime_source == "cli"
    assert analysis.server_name is None
    assert analysis.status is RuntimeDriftStatus.IN_SYNC
    assert analysis.result.differences == ()


def test_reconciliation_service_prefers_contract_server_over_cli_fallback() -> None:
    server = Server.model_validate(
        {
            "server": "production",
            "type": "databricks",
            "host": "https://workspace.example",
            "catalog": "main",
            "schema": "sales",
        }
    )
    loader = _Loader(_contract(servers=[server]))
    provider = _Provider("databricks")
    service = ReconciliationService(
        RuntimeProviderRegistry((provider,)),
        contract_loader=cast(ContractLoader, loader),
    )

    analysis = service.reconcile(
        contract_path="contracts/sales.yaml",
        fallback_platform="warehouse",
        fallback_runtime_target="ignored",
    )

    assert provider.runtime_target == "main.sales"
    assert analysis.platform == "databricks"
    assert analysis.runtime_target == "main.sales"
    assert analysis.runtime_source == "contract"
    assert analysis.server_name == "production"
    assert analysis.status is RuntimeDriftStatus.IN_SYNC
