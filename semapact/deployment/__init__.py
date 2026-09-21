"""Provider-neutral deployment planning and orchestration boundary.

Legacy authorization symbols remain importable for compatibility but are not part of
the canonical public surface.
"""

from semapact.deployment.adapters import (
    DeploymentAdapter,
    RuntimeReleaseMetadata,
    RuntimeReleaseMetadataProjector,
)
from semapact.deployment.authorization import (
    authorize_candidate_deployment,
    validate_candidate_deployment_context,
    validate_contract_release_deployment_context,
)
from semapact.deployment.compatibility import (
    authorize_legacy_deployment as authorize_deployment,
    build_legacy_deployment_plan as build_deployment_plan,
)
from semapact.deployment.compilers import TransitionCompiler
from semapact.deployment.models import (
    DeploymentAction,
    DeploymentActionKind,
    DeploymentAuthorization,
    DeploymentPlan,
    DeploymentPreview,
    DeploymentTarget,
    NativeOperation,
    NativeOperationKind,
)
from semapact.deployment.orchestrator import DeploymentOrchestrator
from semapact.deployment.planner import (
    build_deployment_actions,
    build_deployment_plan_from_source,
)
from semapact.deployment.source import (
    DeploymentSourceSnapshot,
    build_candidate_deployment_source,
    build_contract_release_deployment_source,
)
from semapact.deployment.providers import (
    DeploymentExecutionConfig,
    NativeOperationExecutor,
)
from semapact.deployment.schema_transitions import (
    AdditiveSchemaTransitionPlanner,
    SchemaTransitionPlanner,
)
from semapact.deployment.verification import verify_deployment_convergence

__all__ = [
    "DeploymentAction",
    "DeploymentActionKind",
    "DeploymentAdapter",
    "RuntimeReleaseMetadata",
    "RuntimeReleaseMetadataProjector",
    "DeploymentExecutionConfig",
    "DeploymentOrchestrator",
    "DeploymentPlan",
    "DeploymentPreview",
    "DeploymentTarget",
    "AdditiveSchemaTransitionPlanner",
    "NativeOperation",
    "NativeOperationExecutor",
    "NativeOperationKind",
    "TransitionCompiler",
    "SchemaTransitionPlanner",
    "validate_candidate_deployment_context",
    "validate_contract_release_deployment_context",
    "build_deployment_actions",
    "build_deployment_plan",
    "build_deployment_plan_from_source",
    "build_candidate_deployment_source",
    "build_contract_release_deployment_source",
    "DeploymentSourceSnapshot",
    "verify_deployment_convergence",
]
