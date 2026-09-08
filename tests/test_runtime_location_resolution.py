from __future__ import annotations

from types import SimpleNamespace

import pytest
from open_data_contract_standard.model import OpenDataContractStandard

from semapact.exceptions import ValidationError
from semapact.platforms.runtime_registry import resolve_runtime_location


def _contract(*servers: object) -> OpenDataContractStandard:
    return OpenDataContractStandard.model_construct(
        id="sales-product",
        version="1.0.0",
        servers=list(servers) or None,
        schema_=[],
    )


def _databricks_server(name: str, *, catalog: str, schema: str) -> object:
    return SimpleNamespace(
        server=name,
        type="databricks",
        host="https://workspace.example",
        catalog=catalog,
        schema=schema,
    )


def test_single_contract_server_is_authoritative_over_cli_fallback() -> None:
    location = resolve_runtime_location(
        _contract(_databricks_server("production", catalog="main", schema="sales")),
        fallback_platform="snowflake",
        fallback_runtime_target="ignored.target",
    )

    assert location.platform == "databricks"
    assert location.runtime_target == "main.sales"
    assert location.source == "contract"
    assert location.server_name == "production"
    assert location.contract_server is not None


def test_multiple_contract_servers_require_explicit_server_selection() -> None:
    contract = _contract(
        _databricks_server("staging", catalog="staging", schema="sales"),
        _databricks_server("production", catalog="main", schema="sales"),
    )

    with pytest.raises(ValidationError, match="select one with --server"):
        resolve_runtime_location(contract)

    selected = resolve_runtime_location(contract, server_name="PRODUCTION")
    assert selected.runtime_target == "main.sales"
    assert selected.server_name == "production"


def test_contract_without_servers_uses_complete_cli_fallback() -> None:
    location = resolve_runtime_location(
        _contract(),
        fallback_platform="warehouse",
        fallback_runtime_target="analytics.sales",
    )

    assert location.platform == "warehouse"
    assert location.runtime_target == "analytics.sales"
    assert location.source == "cli"
    assert location.server_name is None
    assert location.contract_server is None


@pytest.mark.parametrize(
    "platform,runtime",
    [
        (None, None),
        ("databricks", None),
        (None, "main.sales"),
    ],
)
def test_contract_without_servers_requires_both_fallback_values(
    platform: str | None,
    runtime: str | None,
) -> None:
    with pytest.raises(
        ValidationError,
        match="provide both --platform and --runtime",
    ):
        resolve_runtime_location(
            _contract(),
            fallback_platform=platform,
            fallback_runtime_target=runtime,
        )


def test_server_selector_is_invalid_when_contract_has_no_servers() -> None:
    with pytest.raises(ValidationError, match="contract defines no servers"):
        resolve_runtime_location(_contract(), server_name="production")
