from __future__ import annotations

from datetime import datetime, timezone

from open_data_contract_standard.model import OpenDataContractStandard, SchemaObject

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
    key = "warehouse"

    def __init__(self) -> None:
        self.runtime_target: str | None = None
        self.specs: tuple[RuntimeAssetSpec, ...] = ()
        self.observed_bindings: tuple[RuntimeAssetBinding, ...] = ()

    def resolve_bindings(
        self,
        *,
        runtime_target: str,
        assets: tuple[RuntimeAssetSpec, ...],
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
        bindings: tuple[RuntimeAssetBinding, ...],
    ) -> ObservedPlatformState:
        self.observed_bindings = tuple(bindings)
        identity = bindings[0].observed_asset
        state = ObservedPlatformState(
            platform=self.key,
            source_identifier="warehouse://test",
            assets=(ObservedAsset(identity=identity, properties=()),),
            captured_at=datetime(2026, 9, 8, 21, 0, tzinfo=timezone.utc),
            fingerprint=None,
        )
        return with_observed_state_fingerprint(state)


def test_reconciliation_service_orchestrates_provider_without_vendor_logic() -> None:
    contract = OpenDataContractStandard.model_construct(
        id="sales-product",
        version="1.0.0",
        schema_=[
            SchemaObject.model_construct(
                name="orders",
                physicalName="fact_orders_v2",
                properties=[],
            )
        ],
    )
    loader = _Loader(contract)
    provider = _Provider()
    service = ReconciliationService(
        RuntimeProviderRegistry((provider,)),
        contract_loader=loader,  # type: ignore[arg-type]
    )

    analysis = service.reconcile(
        contract_path="contracts/sales.yaml",
        platform="WAREHOUSE",
        runtime_target="analytics",
    )

    assert loader.loaded_path == "contracts/sales.yaml"
    assert provider.runtime_target == "analytics"
    assert provider.specs == (
        RuntimeAssetSpec(governed_asset="orders", physical_name="fact_orders_v2"),
    )
    assert provider.observed_bindings == analysis.bindings
    assert analysis.platform == "warehouse"
    assert analysis.runtime_target == "analytics"
    assert analysis.status is RuntimeDriftStatus.IN_SYNC
    assert analysis.result.differences == ()
