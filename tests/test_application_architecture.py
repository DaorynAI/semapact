"""Architecture tests for application/domain/package ownership boundaries."""

from semapact.application.models.governance import GovernanceAnalysis, GovernanceProposal
from semapact.application.models.reconciliation import RuntimeReconciliation
from semapact.application.models.release import ReleasePlanningResult
from semapact.application.services.deployment import DeploymentService
from semapact.application.services.governance import GovernanceService
from semapact.application.services.reconciliation import ReconciliationService
from semapact.application.services.release_planning import ReleasePlanningService
from semapact.application.services.version_authority import VersionAuthorityService
from semapact.services import (
    DeploymentService as LegacyDeploymentService,
    GovernanceAnalysis as LegacyGovernanceAnalysis,
    GovernanceProposal as LegacyGovernanceProposal,
    GovernanceService as LegacyGovernanceService,
    ReconciliationService as LegacyReconciliationService,
    ReleasePlanningResult as LegacyReleasePlanningResult,
    ReleasePlanningService as LegacyReleasePlanningService,
    RuntimeReconciliation as LegacyRuntimeReconciliation,
    VersionAuthorityService as LegacyVersionAuthorityService,
)


def test_application_result_models_have_explicit_model_ownership() -> None:
    assert GovernanceAnalysis.__module__ == "semapact.application.models.governance"
    assert GovernanceProposal.__module__ == "semapact.application.models.governance"
    assert RuntimeReconciliation.__module__ == "semapact.application.models.reconciliation"
    assert ReleasePlanningResult.__module__ == "semapact.application.models.release"


def test_legacy_services_package_is_compatibility_only() -> None:
    assert LegacyGovernanceAnalysis is GovernanceAnalysis
    assert LegacyGovernanceProposal is GovernanceProposal
    assert LegacyRuntimeReconciliation is RuntimeReconciliation
    assert LegacyReleasePlanningResult is ReleasePlanningResult
    assert LegacyGovernanceService is GovernanceService
    assert LegacyReconciliationService is ReconciliationService
    assert LegacyDeploymentService is DeploymentService
    assert LegacyReleasePlanningService is ReleasePlanningService
    assert LegacyVersionAuthorityService is VersionAuthorityService
