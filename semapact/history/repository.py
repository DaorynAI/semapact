"""Storage-neutral typed persistence ports for governance history."""

from __future__ import annotations

from typing import Protocol

from semapact.approval.models import ApprovalRecord
from semapact.contractops import ChangeSet, ReleasePlan
from semapact.deployment import DeploymentAuthorization, DeploymentPlan, DeploymentPreview
from semapact.governance import GovernanceDecision
from semapact.governance.gate import GovernanceOperation
from semapact.history.models import (
    ChangeSetDecisionLink,
    DeploymentRecord,
    HistoryStorageIntegrityIssue,
    ReleaseRecord,
    RuntimeObservationRecord,
    RuntimeReconciliationRecord,
)
from semapact.revision.models import ContractRevision, ContractRevisionSource


class HistoryRepositoryError(RuntimeError):
    """Base error for durable governance-history access."""


class HistoryNotFoundError(HistoryRepositoryError):
    """Requested historical artifact does not exist."""


class HistoryConflictError(HistoryRepositoryError):
    """An immutable artifact ID already exists with different content."""


class HistoryCorruptionError(HistoryRepositoryError):
    """Persisted or supplied historical content fails canonical validation."""


class HistoryIntegrityRepository(Protocol):
    """Backend-specific physical integrity inspection without history mutation."""

    def inspect_history_integrity(self) -> tuple[HistoryStorageIntegrityIssue, ...]: ...


class DecisionHistoryRepository(Protocol):
    """Persistence capability for canonical GovernanceDecision history only."""

    def put_decision(self, decision: GovernanceDecision) -> None: ...
    def get_decision(self, decision_id: str) -> GovernanceDecision: ...
    def list_decisions(self, contract_id: str) -> tuple[GovernanceDecision, ...]: ...


class ChangeSetHistoryRepository(Protocol):
    """Persistence capability for canonical ChangeSet history only."""

    def put_change_set(self, change_set: ChangeSet) -> None: ...
    def get_change_set(self, change_set_id: str) -> ChangeSet: ...
    def list_change_sets(self, contract_id: str) -> tuple[ChangeSet, ...]: ...


class ChangeSetDecisionLinkHistoryRepository(Protocol):
    """Persistence capability for ChangeSet-to-decision audit provenance only."""

    def put_change_set_decision_link(self, link: ChangeSetDecisionLink) -> None: ...

    def list_change_set_decision_links(
        self,
        change_set_id: str,
    ) -> tuple[ChangeSetDecisionLink, ...]: ...


class ApprovalHistoryRepository(Protocol):
    """Persistence capability for immutable ApprovalRecord history only."""

    def put_approval_record(self, record: ApprovalRecord) -> None: ...
    def get_approval_record(self, approval_id: str) -> ApprovalRecord: ...

    def list_approval_records_for_context(
        self,
        *,
        decision_id: str,
        change_set_id: str,
        release_plan_id: str,
        version_resolution_id: str,
        operation: GovernanceOperation,
    ) -> tuple[ApprovalRecord, ...]: ...


class ContractRevisionHistoryRepository(Protocol):
    """Persistence capability for immutable ContractRevision history only."""

    def put_revision(self, revision: ContractRevision) -> None: ...
    def get_revision(self, revision_id: str) -> ContractRevision: ...
    def list_revisions(self, contract_id: str) -> tuple[ContractRevision, ...]: ...


class ContractRevisionSourceHistoryRepository(Protocol):
    """Persistence capability for immutable revision provenance links only."""

    def put_revision_source(self, source: ContractRevisionSource) -> None: ...
    def get_revision_source(self, source_link_id: str) -> ContractRevisionSource: ...

    def list_revision_sources(
        self,
        revision_id: str,
    ) -> tuple[ContractRevisionSource, ...]: ...


class ReleasePlanHistoryRepository(Protocol):
    """Persistence capability for canonical ReleasePlan history only."""

    def put_release_plan(self, release_plan: ReleasePlan) -> None: ...
    def get_release_plan(self, release_plan_id: str) -> ReleasePlan: ...


class ReleaseRecordHistoryRepository(Protocol):
    """Persistence capability for finalized release audit records only."""

    def put_release_record(self, record: ReleaseRecord) -> None: ...
    def get_release_record(self, release_record_id: str) -> ReleaseRecord: ...
    def list_release_records(self, contract_id: str) -> tuple[ReleaseRecord, ...]: ...

    def get_release_record_by_version(
        self,
        contract_id: str,
        contract_version: str,
    ) -> ReleaseRecord: ...


class DeploymentPlanHistoryRepository(Protocol):
    """Persistence capability for canonical DeploymentPlan history only."""

    def put_deployment_plan(self, plan: DeploymentPlan) -> None: ...
    def get_deployment_plan(self, deployment_plan_id: str) -> DeploymentPlan: ...


class DeploymentPreviewHistoryRepository(Protocol):
    """Persistence capability for canonical DeploymentPreview history only."""

    def put_deployment_preview(self, preview: DeploymentPreview) -> None: ...
    def get_deployment_preview(self, deployment_preview_id: str) -> DeploymentPreview: ...


class DeploymentAuthorizationHistoryRepository(Protocol):
    """Persistence capability for canonical DeploymentAuthorization history only."""

    def put_deployment_authorization(
        self,
        authorization: DeploymentAuthorization,
    ) -> None: ...

    def get_deployment_authorization(
        self,
        deployment_authorization_id: str,
    ) -> DeploymentAuthorization: ...


class DeploymentRecordHistoryRepository(Protocol):
    """Persistence capability for terminal deployment execution occurrences only."""

    def put_deployment_record(self, record: DeploymentRecord) -> None: ...
    def get_deployment_record(self, deployment_record_id: str) -> DeploymentRecord: ...

    def list_deployment_records_for_release(
        self,
        release_record_id: str,
    ) -> tuple[DeploymentRecord, ...]: ...

    def list_deployment_records_for_plan(
        self,
        deployment_plan_id: str,
    ) -> tuple[DeploymentRecord, ...]: ...


class RuntimeObservationHistoryRepository(Protocol):
    """Persistence capability for canonical M1 observation evidence envelopes."""

    def put_runtime_observation_record(self, record: RuntimeObservationRecord) -> None: ...
    def get_runtime_observation_record(
        self,
        observation_record_id: str,
    ) -> RuntimeObservationRecord: ...

    def list_runtime_observation_records(
        self,
        source_identifier: str,
    ) -> tuple[RuntimeObservationRecord, ...]: ...


class RuntimeReconciliationHistoryRepository(Protocol):
    """Persistence capability for point-in-time runtime reconciliation history."""

    def put_runtime_reconciliation_record(
        self,
        record: RuntimeReconciliationRecord,
    ) -> None: ...

    def get_runtime_reconciliation_record(
        self,
        runtime_reconciliation_record_id: str,
    ) -> RuntimeReconciliationRecord: ...

    def list_runtime_reconciliation_records(
        self,
        contract_id: str,
    ) -> tuple[RuntimeReconciliationRecord, ...]: ...

    def list_runtime_reconciliation_records_for_source(
        self,
        source_identifier: str,
    ) -> tuple[RuntimeReconciliationRecord, ...]: ...
