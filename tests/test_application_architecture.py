"""Architecture tests for application/domain/package ownership boundaries."""

from semapact.application.models.governance import GovernanceAnalysis, GovernanceProposal
from semapact.application.models.reconciliation import RuntimeReconciliation
from semapact.application.models.release import ReleasePlanningResult
from semapact.application.services.deployment import DeploymentService
from semapact.application.services.governance import GovernanceService
from semapact.application.services.reconciliation import ReconciliationService
from semapact.application.services.release_planning import ReleasePlanningService
from semapact.application.services.version_authority import VersionAuthorityService


def test_application_result_models_have_explicit_model_ownership() -> None:
    assert GovernanceAnalysis.__module__ == "semapact.application.models.governance"
    assert GovernanceProposal.__module__ == "semapact.application.models.governance"
    assert RuntimeReconciliation.__module__ == "semapact.application.models.reconciliation"
    assert ReleasePlanningResult.__module__ == "semapact.application.models.release"


def test_application_services_have_single_canonical_package() -> None:
    assert DeploymentService.__module__ == "semapact.application.services.deployment"
    assert GovernanceService.__module__ == "semapact.application.services.governance"
    assert ReconciliationService.__module__ == "semapact.application.services.reconciliation"
    assert ReleasePlanningService.__module__ == "semapact.application.services.release_planning"
    assert VersionAuthorityService.__module__ == "semapact.application.services.version_authority"
