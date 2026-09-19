from __future__ import annotations

from semapact.deployment import (
    AdditiveSchemaTransitionPlanner,
    DeploymentAdapter,
    DeploymentOrchestrator,
    DeploymentPlatform,
    NativeOperationExecutor,
    SchemaTransitionPlanner,
    TransitionCompiler,
)
from semapact.platforms.databricks.deployment import (
    DatabricksDeploymentAdapter,
    DatabricksStatementExecutor,
)
from semapact.platforms.databricks.platform import DatabricksDeploymentPlatform
from semapact.platforms.databricks.transition_compiler import (
    DatabricksTransitionCompiler,
)
from semapact.schema import SchemaMapper, SqlSchemaMapper


def test_shared_deployment_contracts_own_platform_behavior_seams() -> None:
    assert issubclass(SqlSchemaMapper, SchemaMapper)
    assert issubclass(AdditiveSchemaTransitionPlanner, SchemaTransitionPlanner)
    assert issubclass(DatabricksTransitionCompiler, TransitionCompiler)
    assert issubclass(DatabricksDeploymentPlatform, DeploymentPlatform)
    assert issubclass(DatabricksStatementExecutor, NativeOperationExecutor)


def test_databricks_adapter_is_only_generic_orchestrator_wiring() -> None:
    assert issubclass(DeploymentOrchestrator, DeploymentAdapter)
    assert issubclass(DatabricksDeploymentAdapter, DeploymentOrchestrator)
    assert "preview" not in DatabricksDeploymentAdapter.__dict__
    assert "verify" not in DatabricksDeploymentAdapter.__dict__
    assert "execute" not in DatabricksDeploymentAdapter.__dict__
