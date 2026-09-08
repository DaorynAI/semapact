from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.exceptions import ValidationError
from semapact.observation import (
    ObservedAsset,
    ObservedAssetIdentity,
    ObservedPlatformState,
    ObservedProperty,
    ObservedPropertyIdentity,
    RuntimeAssetBinding,
    RuntimeAssetSpec,
    RuntimeProviderRegistry,
    with_observed_state_fingerprint,
)
from semapact.platforms.databricks import runtime as databricks_runtime
from semapact.platforms.databricks.runtime import DatabricksRuntimeProvider
from semapact.reconciliation import (
    RuntimeReasonCode,
    reconcile_governed_contract,
    runtime_asset_specs_from_contract,
)

CAPTURED_AT = datetime(2026, 9, 8, 20, 0, tzinfo=timezone.utc)


def _contract(*schemas: SchemaObject) -> OpenDataContractStandard:
    return OpenDataContractStandard.model_construct(
        id="sales-product",
        version="1.0.0",
        schema_=list(schemas),
    )


def _observed_asset(
    *,
    namespace: tuple[str, ...],
    name: str,
    property_name: str = "id",
) -> ObservedAsset:
    identity = ObservedAssetIdentity(
        platform="databricks",
        namespace=namespace,
        asset=name,
    )
    return ObservedAsset(
        identity=identity,
        properties=(
            ObservedProperty(
                identity=ObservedPropertyIdentity(
                    asset=identity,
                    property=property_name,
                ),
                physical_type="BIGINT",
                nullable=False,
            ),
        ),
    )


def _observation(*assets: ObservedAsset) -> ObservedPlatformState:
    return with_observed_state_fingerprint(
        ObservedPlatformState(
            platform="databricks",
            source_identifier="https://adb.example",
            assets=tuple(assets),
            captured_at=CAPTURED_AT,
            fingerprint=None,
        )
    )


def test_runtime_asset_specs_keep_logical_identity_separate_from_physical_name() -> None:
    contract = _contract(
        SchemaObject.model_construct(
            name="orders",
            physicalName="fact_orders_v2",
            properties=[],
        ),
        SchemaObject.model_construct(
            name="customers",
            physicalName=None,
            properties=[],
        ),
    )

    assert runtime_asset_specs_from_contract(contract) == (
        RuntimeAssetSpec(governed_asset="customers", physical_name="customers"),
        RuntimeAssetSpec(governed_asset="orders", physical_name="fact_orders_v2"),
    )


def test_explicit_bindings_reconcile_multi_asset_product_without_name_equality() -> None:
    contract = _contract(
        SchemaObject.model_construct(
            name="orders",
            physicalName="fact_orders_v2",
            properties=[
                SchemaProperty(
                    name="id",
                    type="integer",
                    physicalType="BIGINT",
                    required=True,
                )
            ],
        ),
        SchemaObject.model_construct(
            name="customers",
            physicalName="dim_customer",
            properties=[
                SchemaProperty(
                    name="id",
                    type="integer",
                    physicalType="BIGINT",
                    required=True,
                )
            ],
        ),
    )
    orders_identity = ObservedAssetIdentity(
        platform="databricks", namespace=("main", "sales"), asset="fact_orders_v2"
    )
    customers_identity = ObservedAssetIdentity(
        platform="databricks", namespace=("main", "sales"), asset="dim_customer"
    )
    observation = _observation(
        _observed_asset(namespace=("main", "sales"), name="dim_customer"),
        _observed_asset(namespace=("main", "sales"), name="fact_orders_v2"),
    )
    bindings = (
        RuntimeAssetBinding(governed_asset="orders", observed_asset=orders_identity),
        RuntimeAssetBinding(governed_asset="customers", observed_asset=customers_identity),
    )

    result = reconcile_governed_contract(
        contract,
        observation,
        asset_bindings=bindings,
    )

    assert result.differences == ()
    assert result.unverified_paths == ()


def test_missing_bound_runtime_asset_reports_logical_governed_asset() -> None:
    contract = _contract(
        SchemaObject(name="orders", properties=[]),
        SchemaObject(name="customers", properties=[]),
    )
    observation = _observation(
        _observed_asset(namespace=("main", "sales"), name="orders")
    )
    bindings = (
        RuntimeAssetBinding(
            governed_asset="orders",
            observed_asset=ObservedAssetIdentity(
                platform="databricks",
                namespace=("main", "sales"),
                asset="orders",
            ),
        ),
        RuntimeAssetBinding(
            governed_asset="customers",
            observed_asset=ObservedAssetIdentity(
                platform="databricks",
                namespace=("main", "sales"),
                asset="dim_customer",
            ),
        ),
    )

    result = reconcile_governed_contract(
        contract,
        observation,
        asset_bindings=bindings,
    )

    assert len(result.differences) == 1
    difference = result.differences[0]
    assert difference.reason_code is RuntimeReasonCode.RUNTIME_SCHEMA_REMOVED
    assert difference.asset_identity == "customers"
    assert difference.path == "schema[customers]"


def test_runtime_bindings_must_cover_exact_governed_product() -> None:
    contract = _contract(
        SchemaObject(name="orders", properties=[]),
        SchemaObject(name="customers", properties=[]),
    )
    observation = _observation()
    bindings = (
        RuntimeAssetBinding(
            governed_asset="orders",
            observed_asset=ObservedAssetIdentity(
                platform="databricks",
                namespace=("main", "sales"),
                asset="orders",
            ),
        ),
    )

    with pytest.raises(
        ValidationError,
        match="Runtime bindings must cover exactly the governed data-product assets",
    ):
        reconcile_governed_contract(
            contract,
            observation,
            asset_bindings=bindings,
        )


def test_provider_registry_is_vendor_neutral() -> None:
    class _Provider:
        def __init__(self, key: str) -> None:
            self.key = key

        def resolve_bindings(self, **kwargs: object) -> tuple[RuntimeAssetBinding, ...]:
            return ()

        def observe(self, **kwargs: object) -> ObservedPlatformState:
            return _observation()

    registry = RuntimeProviderRegistry(
        (_Provider("databricks"), _Provider("snowflake"))
    )

    assert registry.keys == ("databricks", "snowflake")
    assert registry.get("SNOWFLAKE").key == "snowflake"


class _FakeTableInfo:
    def __init__(self, *, catalog: str, schema: str, name: str) -> None:
        self._payload = {
            "catalog_name": catalog,
            "schema_name": schema,
            "name": name,
            "full_name": f"{catalog}.{schema}.{name}",
            "columns": [
                {
                    "name": "id",
                    "type_text": "BIGINT",
                    "nullable": False,
                    "position": 0,
                }
            ],
        }

    def as_dict(self) -> dict[str, object]:
        return self._payload


class _FakeNotFound(Exception):
    pass


def test_databricks_provider_resolves_and_observes_complete_bound_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tables = {
        "main.sales.fact_orders_v2": _FakeTableInfo(
            catalog="main", schema="sales", name="fact_orders_v2"
        )
    }

    class _Tables:
        def get(self, full_name: str) -> _FakeTableInfo:
            try:
                return tables[full_name]
            except KeyError:
                raise _FakeNotFound(full_name) from None

    provider = DatabricksRuntimeProvider(
        client=SimpleNamespace(tables=_Tables()),
        source_identifier="https://adb.example/",
    )
    monkeypatch.setattr(
        databricks_runtime,
        "_load_databricks_not_found_error",
        lambda: _FakeNotFound,
    )
    specs = (
        RuntimeAssetSpec(governed_asset="customers", physical_name="dim_customer"),
        RuntimeAssetSpec(governed_asset="orders", physical_name="fact_orders_v2"),
    )

    bindings = provider.resolve_bindings(runtime_target="main.sales", assets=specs)
    state = provider.observe(bindings=bindings)

    assert [binding.governed_asset for binding in bindings] == ["customers", "orders"]
    assert bindings[0].observed_asset.namespace == ("main", "sales")
    assert bindings[1].observed_asset.asset == "fact_orders_v2"
    assert [asset.identity.asset for asset in state.assets] == ["fact_orders_v2"]
    assert state.platform == "databricks"
    assert state.source_identifier == "https://adb.example"
    assert state.fingerprint is not None
