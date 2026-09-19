"""Platform composition contract for runtime and deployment integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping

from open_data_contract_standard.model import Server

from semapact.deployment.adapters import DeploymentAdapter
from semapact.observation.providers import RuntimeProvider


class PlatformFactory(ABC):
    """Compose one platform's read/write implementations lazily."""

    key: str

    @abstractmethod
    def runtime_target_from_server(self, server: Server) -> str:
        """Project one ODCS server into this platform's runtime target."""
        raise NotImplementedError

    @abstractmethod
    def create_runtime_provider(
        self,
        *,
        contract_server: Server | None = None,
    ) -> RuntimeProvider:
        raise NotImplementedError

    @abstractmethod
    def create_deployment_adapter(
        self,
        *,
        contract_server: Server | None = None,
        execution_options: Mapping[str, object] | None = None,
    ) -> DeploymentAdapter:
        raise NotImplementedError
