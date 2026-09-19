from __future__ import annotations

import pytest

from open_data_contract_standard.model import OpenDataContractStandard, Server

from semapact.deployment import DeploymentAdapter, DeploymentExecutionConfig
from semapact.exceptions import ValidationError
from semapact.platforms.factories import PlatformFactory
from semapact.platforms import runtime_registry


class _FakeRuntimeProvider:
    key = "fake"

    def resolve_bindings(self, *, runtime_target, assets):
        return ()

    def observe(self, *, bindings):
        raise AssertionError("observation is not needed for factory composition test")


class _FakeDeploymentAdapter(DeploymentAdapter):
    key = "fake"

    def validate(self, plan):
        raise AssertionError("validation is not needed for factory composition test")

    def preview(self, plan):
        raise AssertionError("preview is not needed for factory composition test")

    def verify(self, plan):
        raise AssertionError("verify is not needed for factory composition test")

    def execute(self, plan, preview, authorization):
        raise AssertionError("execute is not needed for factory composition test")


class _FakePlatformFactory(PlatformFactory):
    key = "fake"

    def __init__(self) -> None:
        self.provider = _FakeRuntimeProvider()
        self.adapter = _FakeDeploymentAdapter()
        self.execution_config: DeploymentExecutionConfig | None = None

    def runtime_target_from_server(self, server: Server) -> str:
        return "tenant.dataset"

    def create_runtime_provider(self, *, contract_server=None):
        return self.provider

    def create_deployment_adapter(
        self,
        *,
        contract_server=None,
        execution_config=None,
    ):
        self.execution_config = execution_config
        return self.adapter


def _contract(server: Server) -> OpenDataContractStandard:
    return OpenDataContractStandard.model_construct(
        id="fake-product",
        version="1.0.0",
        servers=[server],
        schema_=[],
    )


def test_one_factory_loader_extends_all_platform_composition_paths(
    monkeypatch,
) -> None:
    factory = _FakePlatformFactory()
    monkeypatch.setitem(
        runtime_registry._PLATFORM_FACTORY_LOADERS,
        "fake",
        lambda: factory,
    )
    server = Server.model_construct(
        server="production",
        type="fake",
        host="https://fake.example",
    )

    location = runtime_registry.resolve_runtime_location(_contract(server))
    provider = runtime_registry.create_runtime_provider_registry("fake").get("fake")
    adapter = runtime_registry.create_deployment_adapter(
        "fake",
        execution_config=DeploymentExecutionConfig(platform="fake"),
    )

    assert location.platform == "fake"
    assert location.runtime_target == "tenant.dataset"
    assert provider is factory.provider
    assert adapter is factory.adapter
    assert factory.execution_config == DeploymentExecutionConfig(platform="fake")



def test_registry_rejects_execution_config_for_another_platform(
    monkeypatch,
) -> None:
    factory = _FakePlatformFactory()
    monkeypatch.setitem(
        runtime_registry._PLATFORM_FACTORY_LOADERS,
        "fake",
        lambda: factory,
    )

    with pytest.raises(ValidationError, match="config platform"):
        runtime_registry.create_deployment_adapter(
            "fake",
            execution_config=DeploymentExecutionConfig(platform="other"),
        )
