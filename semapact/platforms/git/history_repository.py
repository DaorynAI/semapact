"""Immutable governance-history persistence in a Git working tree.

The adapter owns file layout only. It does not invoke Git, create commits, or create
pull requests; normal GitOps tooling can version the deterministic files it writes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError as PydanticValidationError

from semapact.approval.integrity import validate_approval_record_identity
from semapact.approval.models import ApprovalRecord
from semapact.contractops import ChangeSet, ReleasePlan
from semapact.contractops.integrity import (
    validate_change_set_identity,
    validate_release_plan_identity,
)
from semapact.deployment import DeploymentAuthorization, DeploymentPlan, DeploymentPreview
from semapact.deployment.compatibility import (
    parse_deployment_authorization_payload,
    parse_deployment_plan_payload,
    serialize_deployment_authorization_payload,
    serialize_deployment_plan_payload,
)
from semapact.deployment.models import (
    validate_deployment_authorization_identity,
    validate_deployment_plan_identity,
    validate_deployment_preview_identity,
)
from semapact.governance import GovernanceDecision
from semapact.governance.gate import GovernanceOperation
from semapact.history import (
    ChangeSetDecisionLink,
    ContractReleaseRecord,
    DeploymentRecord,
    HistoryConflictError,
    HistoryCorruptionError,
    HistoryIntegrityIssueCode,
    HistoryNotFoundError,
    HistoryStorageIntegrityIssue,
    ReleaseRecord,
    RuntimeObservationRecord,
    RuntimeReconciliationRecord,
)
from semapact.history.integrity import (
    validate_contract_release_record_identity,
    validate_deployment_record_identity,
    validate_release_record_identity,
    validate_runtime_observation_record_identity,
    validate_runtime_reconciliation_record_identity,
)
from semapact.revision.integrity import (
    validate_contract_revision_identity,
    validate_contract_revision_source_identity,
)
from semapact.revision.models import ContractRevision, ContractRevisionSource
from semapact.utils.deterministic import canonical_compact_json


T = TypeVar("T", bound=BaseModel)
_SAFE_ARTIFACT_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_CHECKSUM_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class _HistoryKindSpec(Generic[T]):
    """Single source of Git-layout and rehydration metadata for one history kind."""

    directory: str
    model_type: type[T]
    id_attribute: str
    integrity_validator: Callable[[T], None] | None = None
    parser: Callable[[Mapping[str, Any]], T] | None = None
    serializer: Callable[[T], dict[str, Any]] | None = None


_DECISIONS = _HistoryKindSpec(
    "decisions",
    GovernanceDecision,
    "decision_id",
)
_CHANGE_SETS = _HistoryKindSpec(
    "change_sets",
    ChangeSet,
    "change_set_id",
    validate_change_set_identity,
)
_CHANGE_SET_DECISIONS = _HistoryKindSpec(
    "change_set_decisions",
    ChangeSetDecisionLink,
    "decision_id",
)
_APPROVAL_RECORDS = _HistoryKindSpec(
    "approval_records",
    ApprovalRecord,
    "approval_id",
    validate_approval_record_identity,
)
_CONTRACT_REVISIONS = _HistoryKindSpec(
    "contract_revisions",
    ContractRevision,
    "revision_id",
    validate_contract_revision_identity,
)
_CONTRACT_REVISION_SOURCES = _HistoryKindSpec(
    "contract_revision_sources",
    ContractRevisionSource,
    "source_link_id",
    validate_contract_revision_source_identity,
)
_RELEASE_PLANS = _HistoryKindSpec(
    "release_plans",
    ReleasePlan,
    "release_plan_id",
    validate_release_plan_identity,
)
_RELEASE_RECORDS = _HistoryKindSpec(
    "release_records",
    ReleaseRecord,
    "release_record_id",
    validate_release_record_identity,
)
_CONTRACT_RELEASES = _HistoryKindSpec(
    "contract_releases",
    ContractReleaseRecord,
    "contract_release_id",
    validate_contract_release_record_identity,
)
_DEPLOYMENT_PLANS = _HistoryKindSpec(
    "deployment_plans",
    DeploymentPlan,
    "deployment_plan_id",
    validate_deployment_plan_identity,
    parse_deployment_plan_payload,
    serialize_deployment_plan_payload,
)
_DEPLOYMENT_PREVIEWS = _HistoryKindSpec(
    "deployment_previews",
    DeploymentPreview,
    "deployment_preview_id",
    validate_deployment_preview_identity,
)
_DEPLOYMENT_AUTHORIZATIONS = _HistoryKindSpec(
    "deployment_authorizations",
    DeploymentAuthorization,
    "deployment_authorization_id",
    validate_deployment_authorization_identity,
    parse_deployment_authorization_payload,
    serialize_deployment_authorization_payload,
)
_DEPLOYMENT_RECORDS = _HistoryKindSpec(
    "deployment_records",
    DeploymentRecord,
    "deployment_record_id",
    validate_deployment_record_identity,
)
_RUNTIME_OBSERVATIONS = _HistoryKindSpec(
    "runtime_observations",
    RuntimeObservationRecord,
    "observation_record_id",
    validate_runtime_observation_record_identity,
)
_RUNTIME_RECONCILIATIONS = _HistoryKindSpec(
    "runtime_reconciliations",
    RuntimeReconciliationRecord,
    "runtime_reconciliation_record_id",
    validate_runtime_reconciliation_record_identity,
)

_HISTORY_KIND_SPECS: dict[str, _HistoryKindSpec[BaseModel]] = {
    spec.directory: spec
    for spec in (
        _DECISIONS,
        _CHANGE_SETS,
        _CHANGE_SET_DECISIONS,
        _APPROVAL_RECORDS,
        _CONTRACT_REVISIONS,
        _CONTRACT_REVISION_SOURCES,
        _RELEASE_PLANS,
        _RELEASE_RECORDS,
        _CONTRACT_RELEASES,
        _DEPLOYMENT_PLANS,
        _DEPLOYMENT_PREVIEWS,
        _DEPLOYMENT_AUTHORIZATIONS,
        _DEPLOYMENT_RECORDS,
        _RUNTIME_OBSERVATIONS,
        _RUNTIME_RECONCILIATIONS,
    )
}


class GitWorkingTreeHistoryRepository:
    """Shared Git backend implementing narrow typed history capabilities."""

    def __init__(
        self,
        repository_root: str | Path,
        *,
        state_directory: str | Path = ".semapact/history",
    ) -> None:
        repository_path = Path(repository_root).resolve(strict=False)
        state_path = Path(state_directory)
        if state_path.is_absolute():
            raise ValueError("history state_directory must be repository-relative")
        if ".." in state_path.parts:
            raise ValueError("history state_directory must not contain '..'")
        history_root = (repository_path / state_path).resolve(strict=False)
        if not history_root.is_relative_to(repository_path):
            raise ValueError("history state_directory must remain inside repository_root")
        self._repository_root = repository_path
        self._history_root = history_root

    def put_decision(self, decision: GovernanceDecision) -> None:
        self._put(_DECISIONS, decision.decision_id, decision)

    def get_decision(self, decision_id: str) -> GovernanceDecision:
        return self._get(_DECISIONS, decision_id)

    def list_decisions(self, contract_id: str) -> tuple[GovernanceDecision, ...]:
        contract_id = _required_text(contract_id, "contract_id")
        return tuple(
            record
            for record in self._list(_DECISIONS)
            if record.contract_id == contract_id
        )

    def put_change_set(self, change_set: ChangeSet) -> None:
        self._put(_CHANGE_SETS, change_set.change_set_id, change_set)

    def get_change_set(self, change_set_id: str) -> ChangeSet:
        return self._get(_CHANGE_SETS, change_set_id)

    def list_change_sets(self, contract_id: str) -> tuple[ChangeSet, ...]:
        contract_id = _required_text(contract_id, "contract_id")
        return tuple(
            record
            for record in self._list(_CHANGE_SETS)
            if record.contract_id == contract_id
        )

    def put_change_set_decision_link(self, link: ChangeSetDecisionLink) -> None:
        if not isinstance(link, ChangeSetDecisionLink):
            raise TypeError(
                "link must be ChangeSetDecisionLink, "
                f"got {type(link).__name__}"
            )
        change_set_id = _safe_artifact_id(link.change_set_id)
        self._put(
            _CHANGE_SET_DECISIONS,
            link.decision_id,
            link,
            directory=f"{_CHANGE_SET_DECISIONS.directory}/{change_set_id}",
        )

    def list_change_set_decision_links(
        self,
        change_set_id: str,
    ) -> tuple[ChangeSetDecisionLink, ...]:
        change_set_id = _safe_artifact_id(change_set_id)
        records = self._list(
            _CHANGE_SET_DECISIONS,
            directory=f"{_CHANGE_SET_DECISIONS.directory}/{change_set_id}",
        )
        for record in records:
            if record.change_set_id != change_set_id:
                raise HistoryCorruptionError(
                    "Persisted ChangeSetDecisionLink does not match its ChangeSet path"
                )
        return records

    def put_approval_record(self, record: ApprovalRecord) -> None:
        self._put(_APPROVAL_RECORDS, record.approval_id, record)

    def get_approval_record(self, approval_id: str) -> ApprovalRecord:
        return self._get(_APPROVAL_RECORDS, approval_id)

    def list_approval_records_for_context(
        self,
        *,
        decision_id: str,
        change_set_id: str,
        release_plan_id: str,
        version_resolution_id: str,
        operation: GovernanceOperation,
    ) -> tuple[ApprovalRecord, ...]:
        decision_id = _required_text(decision_id, "decision_id")
        change_set_id = _required_text(change_set_id, "change_set_id")
        release_plan_id = _required_text(release_plan_id, "release_plan_id")
        version_resolution_id = _required_text(
            version_resolution_id,
            "version_resolution_id",
        )
        if not isinstance(operation, GovernanceOperation):
            raise TypeError(
                "operation must be GovernanceOperation, "
                f"got {type(operation).__name__}"
            )
        return tuple(
            record
            for record in self._list(_APPROVAL_RECORDS)
            if record.decision_id == decision_id
            and record.change_set_id == change_set_id
            and record.release_plan_id == release_plan_id
            and record.version_resolution_id == version_resolution_id
            and record.operation is operation
        )

    def put_revision(self, revision: ContractRevision) -> None:
        self._put(_CONTRACT_REVISIONS, revision.revision_id, revision)

    def get_revision(self, revision_id: str) -> ContractRevision:
        return self._get(_CONTRACT_REVISIONS, revision_id)

    def list_revisions(self, contract_id: str) -> tuple[ContractRevision, ...]:
        contract_id = _required_text(contract_id, "contract_id")
        return tuple(
            record
            for record in self._list(_CONTRACT_REVISIONS)
            if str(record.contract.id or "") == contract_id
        )

    def put_revision_source(self, source: ContractRevisionSource) -> None:
        self._put(_CONTRACT_REVISION_SOURCES, source.source_link_id, source)

    def get_revision_source(self, source_link_id: str) -> ContractRevisionSource:
        return self._get(_CONTRACT_REVISION_SOURCES, source_link_id)

    def list_revision_sources(
        self,
        revision_id: str,
    ) -> tuple[ContractRevisionSource, ...]:
        revision_id = _required_text(revision_id, "revision_id")
        return tuple(
            record
            for record in self._list(_CONTRACT_REVISION_SOURCES)
            if record.revision_id == revision_id
        )

    def put_release_plan(self, release_plan: ReleasePlan) -> None:
        self._put(_RELEASE_PLANS, release_plan.release_plan_id, release_plan)

    def get_release_plan(self, release_plan_id: str) -> ReleasePlan:
        return self._get(_RELEASE_PLANS, release_plan_id)

    def put_release_record(self, record: ReleaseRecord) -> None:
        if not isinstance(record, ReleaseRecord):
            raise TypeError(
                f"record must be ReleaseRecord, got {type(record).__name__}"
            )
        validate_release_record_identity(record)
        for existing in self.list_release_records(record.contract_id):
            if (
                existing.contract_version == record.contract_version
                and existing.release_record_id != record.release_record_id
            ):
                raise HistoryConflictError(
                    "A different ReleaseRecord already exists for "
                    f"{record.contract_id!r} version {record.contract_version!r}"
                )
        self._put(_RELEASE_RECORDS, record.release_record_id, record)

    def get_release_record(self, release_record_id: str) -> ReleaseRecord:
        return self._get(_RELEASE_RECORDS, release_record_id)

    def list_release_records(self, contract_id: str) -> tuple[ReleaseRecord, ...]:
        contract_id = _required_text(contract_id, "contract_id")
        return tuple(
            record
            for record in self._list(_RELEASE_RECORDS)
            if record.contract_id == contract_id
        )

    def get_release_record_by_version(
        self,
        contract_id: str,
        contract_version: str,
    ) -> ReleaseRecord:
        contract_id = _required_text(contract_id, "contract_id")
        contract_version = _required_text(contract_version, "contract_version")
        matches = tuple(
            record
            for record in self.list_release_records(contract_id)
            if record.contract_version == contract_version
        )
        if not matches:
            raise HistoryNotFoundError(
                f"ReleaseRecord for {contract_id!r} version {contract_version!r} was not found"
            )
        if len(matches) != 1:
            raise HistoryCorruptionError(
                f"Multiple ReleaseRecords exist for {contract_id!r} version {contract_version!r}"
            )
        return matches[0]

    def put_contract_release(self, record: ContractReleaseRecord) -> None:
        if not isinstance(record, ContractReleaseRecord):
            raise TypeError(
                "record must be ContractReleaseRecord, "
                f"got {type(record).__name__}"
            )
        validate_contract_release_record_identity(record)
        for existing in self.list_contract_releases(record.contract_id):
            if (
                existing.contract_version == record.contract_version
                and existing.contract_release_id != record.contract_release_id
            ):
                raise HistoryConflictError(
                    "A different ContractReleaseRecord already exists for "
                    f"{record.contract_id!r} version {record.contract_version!r}"
                )
        self._put(_CONTRACT_RELEASES, record.contract_release_id, record)

    def get_contract_release(
        self,
        contract_release_id: str,
    ) -> ContractReleaseRecord:
        return self._get(_CONTRACT_RELEASES, contract_release_id)

    def list_contract_releases(
        self,
        contract_id: str,
    ) -> tuple[ContractReleaseRecord, ...]:
        contract_id = _required_text(contract_id, "contract_id")
        return tuple(
            record
            for record in self._list(_CONTRACT_RELEASES)
            if record.contract_id == contract_id
        )

    def get_contract_release_by_version(
        self,
        contract_id: str,
        contract_version: str,
    ) -> ContractReleaseRecord:
        contract_id = _required_text(contract_id, "contract_id")
        contract_version = _required_text(contract_version, "contract_version")
        matches = tuple(
            record
            for record in self.list_contract_releases(contract_id)
            if record.contract_version == contract_version
        )
        if not matches:
            raise HistoryNotFoundError(
                f"ContractReleaseRecord for {contract_id!r} "
                f"version {contract_version!r} was not found"
            )
        if len(matches) != 1:
            raise HistoryCorruptionError(
                f"Multiple ContractReleaseRecords exist for {contract_id!r} "
                f"version {contract_version!r}"
            )
        return matches[0]

    def put_deployment_plan(self, plan: DeploymentPlan) -> None:
        self._put(_DEPLOYMENT_PLANS, plan.deployment_plan_id, plan)

    def get_deployment_plan(self, deployment_plan_id: str) -> DeploymentPlan:
        return self._get(_DEPLOYMENT_PLANS, deployment_plan_id)

    def put_deployment_preview(self, preview: DeploymentPreview) -> None:
        self._put(_DEPLOYMENT_PREVIEWS, preview.deployment_preview_id, preview)

    def get_deployment_preview(self, deployment_preview_id: str) -> DeploymentPreview:
        return self._get(_DEPLOYMENT_PREVIEWS, deployment_preview_id)

    def put_deployment_authorization(
        self,
        authorization: DeploymentAuthorization,
    ) -> None:
        self._put(
            _DEPLOYMENT_AUTHORIZATIONS,
            authorization.deployment_authorization_id,
            authorization,
        )

    def get_deployment_authorization(
        self,
        deployment_authorization_id: str,
    ) -> DeploymentAuthorization:
        return self._get(_DEPLOYMENT_AUTHORIZATIONS, deployment_authorization_id)

    def put_deployment_record(self, record: DeploymentRecord) -> None:
        self._put(_DEPLOYMENT_RECORDS, record.deployment_record_id, record)

    def get_deployment_record(self, deployment_record_id: str) -> DeploymentRecord:
        return self._get(_DEPLOYMENT_RECORDS, deployment_record_id)

    def list_deployment_records_for_release(
        self,
        release_record_id: str,
    ) -> tuple[DeploymentRecord, ...]:
        release_record_id = _required_text(release_record_id, "release_record_id")
        return tuple(
            record
            for record in self._list(_DEPLOYMENT_RECORDS)
            if record.release_record_id == release_record_id
        )

    def list_deployment_records_for_plan(
        self,
        deployment_plan_id: str,
    ) -> tuple[DeploymentRecord, ...]:
        deployment_plan_id = _required_text(deployment_plan_id, "deployment_plan_id")
        return tuple(
            record
            for record in self._list(_DEPLOYMENT_RECORDS)
            if record.deployment_plan_id == deployment_plan_id
        )

    def put_runtime_observation_record(self, record: RuntimeObservationRecord) -> None:
        self._put(_RUNTIME_OBSERVATIONS, record.observation_record_id, record)

    def get_runtime_observation_record(
        self,
        observation_record_id: str,
    ) -> RuntimeObservationRecord:
        return self._get(_RUNTIME_OBSERVATIONS, observation_record_id)

    def list_runtime_observation_records(
        self,
        source_identifier: str,
    ) -> tuple[RuntimeObservationRecord, ...]:
        source_identifier = _required_text(source_identifier, "source_identifier")
        return tuple(
            record
            for record in self._list(_RUNTIME_OBSERVATIONS)
            if record.observation.source_identifier == source_identifier
        )

    def put_runtime_reconciliation_record(
        self,
        record: RuntimeReconciliationRecord,
    ) -> None:
        self._put(
            _RUNTIME_RECONCILIATIONS,
            record.runtime_reconciliation_record_id,
            record,
        )

    def get_runtime_reconciliation_record(
        self,
        runtime_reconciliation_record_id: str,
    ) -> RuntimeReconciliationRecord:
        return self._get(
            _RUNTIME_RECONCILIATIONS,
            runtime_reconciliation_record_id,
        )

    def list_runtime_reconciliation_records(
        self,
        contract_id: str,
    ) -> tuple[RuntimeReconciliationRecord, ...]:
        contract_id = _required_text(contract_id, "contract_id")
        return tuple(
            record
            for record in self._list(_RUNTIME_RECONCILIATIONS)
            if record.result.contract_id == contract_id
        )

    def list_runtime_reconciliation_records_for_source(
        self,
        source_identifier: str,
    ) -> tuple[RuntimeReconciliationRecord, ...]:
        source_identifier = _required_text(source_identifier, "source_identifier")
        return tuple(
            record
            for record in self._list(_RUNTIME_RECONCILIATIONS)
            if record.result.observation_source_identifier == source_identifier
        )

    def inspect_history_integrity(self) -> tuple[HistoryStorageIntegrityIssue, ...]:
        """Inspect physical history artifacts and checksum evidence without mutation."""
        root_issue = self._inspect_history_root()
        if root_issue is not None:
            return (root_issue,)

        issues = [
            *self._inspect_history_artifacts(),
            *self._inspect_orphan_checksums(),
        ]
        return tuple(sorted(issues, key=_integrity_issue_sort_key))

    def _inspect_history_root(self) -> HistoryStorageIntegrityIssue | None:
        if not self._history_root.exists():
            return None
        if self._path_is_within_history(self._history_root):
            return None
        return self._integrity_issue(
            HistoryIntegrityIssueCode.UNKNOWN_ARTIFACT_LAYOUT,
            self._history_root,
            detail="resolved history root escapes repository containment",
        )

    def _inspect_history_artifacts(self) -> list[HistoryStorageIntegrityIssue]:
        if not self._history_root.exists():
            return []

        issues: list[HistoryStorageIntegrityIssue] = []
        for path in sorted(self._history_root.rglob("*.json"), key=Path.as_posix):
            issues.extend(self._inspect_history_artifact(path))
        return issues

    def _inspect_history_artifact(
        self,
        path: Path,
    ) -> tuple[HistoryStorageIntegrityIssue, ...]:
        if not self._path_is_within_history(path):
            return (
                self._integrity_issue(
                    HistoryIntegrityIssueCode.UNKNOWN_ARTIFACT_LAYOUT,
                    path,
                    detail="resolved artifact path escapes history root",
                ),
            )

        resolved = self._resolve_history_spec(path)
        if resolved is None:
            return (
                self._integrity_issue(
                    HistoryIntegrityIssueCode.UNKNOWN_ARTIFACT_LAYOUT,
                    path,
                    detail="artifact path does not match a canonical history layout",
                ),
            )

        spec, artifact_id, parent_change_set_id = resolved
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            return (
                self._integrity_issue(
                    HistoryIntegrityIssueCode.ARTIFACT_INVALID,
                    path,
                    artifact_kind=spec.directory,
                    artifact_id=artifact_id,
                    detail=f"artifact could not be read: {exc}",
                ),
            )

        issues = list(
            self._inspect_checksum(
                path,
                raw,
                artifact_kind=spec.directory,
                artifact_id=artifact_id,
            )
        )

        try:
            artifact = _parse_artifact_json(spec, raw)
            if spec.integrity_validator is not None:
                spec.integrity_validator(artifact)
        except (PydanticValidationError, ValueError, TypeError) as exc:
            issues.append(
                self._integrity_issue(
                    HistoryIntegrityIssueCode.ARTIFACT_INVALID,
                    path,
                    artifact_kind=spec.directory,
                    artifact_id=artifact_id,
                    detail=f"artifact failed canonical validation: {exc}",
                )
            )
            return tuple(issues)

        actual_id = getattr(artifact, spec.id_attribute)
        if actual_id != artifact_id:
            issues.append(
                self._integrity_issue(
                    HistoryIntegrityIssueCode.IDENTITY_MISMATCH,
                    path,
                    artifact_kind=spec.directory,
                    artifact_id=artifact_id,
                    detail=(
                        f"embedded {spec.id_attribute} {actual_id!r} does not match "
                        f"file identity {artifact_id!r}"
                    ),
                )
            )

        provenance_issue = self._inspect_path_provenance(
            path,
            spec=spec,
            artifact=artifact,
            artifact_id=artifact_id,
            parent_change_set_id=parent_change_set_id,
        )
        if provenance_issue is not None:
            issues.append(provenance_issue)

        return tuple(issues)

    def _inspect_path_provenance(
        self,
        path: Path,
        *,
        spec: _HistoryKindSpec[BaseModel],
        artifact: BaseModel,
        artifact_id: str,
        parent_change_set_id: str | None,
    ) -> HistoryStorageIntegrityIssue | None:
        if spec is not _CHANGE_SET_DECISIONS or parent_change_set_id is None:
            return None
        if not isinstance(artifact, ChangeSetDecisionLink):
            return None
        if artifact.change_set_id == parent_change_set_id:
            return None
        return self._integrity_issue(
            HistoryIntegrityIssueCode.PATH_PROVENANCE_MISMATCH,
            path,
            artifact_kind=spec.directory,
            artifact_id=artifact_id,
            detail=(
                f"embedded change_set_id {artifact.change_set_id!r} does not match "
                f"path provenance {parent_change_set_id!r}"
            ),
        )

    def _inspect_orphan_checksums(self) -> list[HistoryStorageIntegrityIssue]:
        if not self._history_root.exists():
            return []

        issues: list[HistoryStorageIntegrityIssue] = []
        for checksum_path in sorted(
            self._history_root.rglob("*.json.sha256"),
            key=Path.as_posix,
        ):
            if not self._path_is_within_history(checksum_path):
                issues.append(
                    self._integrity_issue(
                        HistoryIntegrityIssueCode.UNKNOWN_ARTIFACT_LAYOUT,
                        checksum_path,
                        detail="resolved checksum path escapes history root",
                    )
                )
                continue

            artifact_path = checksum_path.with_name(
                checksum_path.name.removesuffix(".sha256")
            )
            if not artifact_path.is_file():
                issues.append(
                    self._integrity_issue(
                        HistoryIntegrityIssueCode.ORPHAN_CHECKSUM,
                        checksum_path,
                        detail="checksum sidecar has no corresponding JSON artifact",
                    )
                )
        return issues

    def _put(
        self,
        spec: _HistoryKindSpec[T],
        artifact_id: str,
        artifact: T,
        *,
        directory: str | None = None,
    ) -> None:
        artifact_id = _safe_artifact_id(artifact_id)
        canonical = self._validated_canonical_json(
            spec,
            artifact,
            expected_id=artifact_id,
        )
        path = self._artifact_path(spec, artifact_id, directory=directory)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._assert_path_within_history(path)

        if path.exists():
            self._require_idempotent_existing(
                spec,
                path,
                canonical=canonical,
                expected_id=artifact_id,
            )
            self._ensure_checksum(path)
            return

        created = self._publish_create_only(path, canonical)
        if not created:
            self._require_idempotent_existing(
                spec,
                path,
                canonical=canonical,
                expected_id=artifact_id,
            )
        self._ensure_checksum(path)

    def _get(
        self,
        spec: _HistoryKindSpec[T],
        artifact_id: str,
        *,
        directory: str | None = None,
    ) -> T:
        artifact_id = _safe_artifact_id(artifact_id)
        path = self._artifact_path(spec, artifact_id, directory=directory)
        if not path.is_file():
            raise HistoryNotFoundError(
                f"{spec.model_type.__name__} {artifact_id!r} was not found"
            )
        return self._read_validated(spec, path, expected_id=artifact_id)

    def _list(
        self,
        spec: _HistoryKindSpec[T],
        *,
        directory: str | None = None,
    ) -> tuple[T, ...]:
        resolved_directory = directory or spec.directory
        path = self._history_root / resolved_directory
        self._assert_path_within_history(path)
        if not path.is_dir():
            return ()

        records: list[T] = []
        for artifact_path in sorted(path.glob("*.json"), key=_path_name):
            artifact_id = _safe_artifact_id(artifact_path.stem)
            records.append(
                self._read_validated(
                    spec,
                    artifact_path,
                    expected_id=artifact_id,
                )
            )
        return tuple(records)

    def _require_idempotent_existing(
        self,
        spec: _HistoryKindSpec[T],
        path: Path,
        *,
        canonical: str,
        expected_id: str,
    ) -> None:
        existing = self._read_validated(spec, path, expected_id=expected_id)
        existing_canonical = _canonical_artifact_json(spec, existing)
        if existing_canonical != canonical:
            raise HistoryConflictError(
                f"{spec.model_type.__name__} {expected_id!r} already exists with different content"
            )

    def _read_validated(
        self,
        spec: _HistoryKindSpec[T],
        path: Path,
        *,
        expected_id: str,
    ) -> T:
        self._assert_path_within_history(path)
        try:
            raw = path.read_text(encoding="utf-8")
            self._verify_checksum_if_present(path, raw)
            artifact = _parse_artifact_json(spec, raw)
            if spec.integrity_validator is not None:
                spec.integrity_validator(artifact)
        except HistoryCorruptionError:
            raise
        except (OSError, PydanticValidationError, ValueError, TypeError) as exc:
            raise HistoryCorruptionError(
                f"Persisted {spec.model_type.__name__} {expected_id!r} is invalid"
            ) from exc

        actual_id = getattr(artifact, spec.id_attribute)
        if actual_id != expected_id:
            raise HistoryCorruptionError(
                f"Persisted {spec.model_type.__name__} identity does not match its file identity"
            )
        return artifact

    def _validated_canonical_json(
        self,
        spec: _HistoryKindSpec[T],
        artifact: T,
        *,
        expected_id: str,
    ) -> str:
        if not isinstance(artifact, spec.model_type):
            raise TypeError(
                f"artifact must be {spec.model_type.__name__}, got {type(artifact).__name__}"
            )
        try:
            canonical = _canonical_artifact_json(spec, artifact)
            validated = _parse_artifact_json(spec, canonical)
            if spec.integrity_validator is not None:
                spec.integrity_validator(validated)
        except (PydanticValidationError, ValueError, TypeError) as exc:
            raise HistoryCorruptionError(
                f"Supplied {spec.model_type.__name__} {expected_id!r} is invalid"
            ) from exc
        if getattr(validated, spec.id_attribute) != expected_id:
            raise HistoryCorruptionError(
                f"Supplied {spec.model_type.__name__} identity does not match its artifact ID"
            )
        return canonical

    def _artifact_path(
        self,
        spec: _HistoryKindSpec[BaseModel],
        artifact_id: str,
        *,
        directory: str | None = None,
    ) -> Path:
        path = self._history_root / (directory or spec.directory) / f"{artifact_id}.json"
        self._assert_path_within_history(path)
        return path

    def _ensure_checksum(self, path: Path) -> None:
        self._assert_path_within_history(path)
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise HistoryCorruptionError(
                f"Persisted history artifact {self._storage_reference(path)!r} cannot be read"
            ) from exc

        checksum_path = _checksum_path(path)
        expected = _checksum_record(raw)
        if checksum_path.exists():
            self._verify_checksum_if_present(path, raw)
            return

        created = self._publish_create_only(checksum_path, expected)
        if not created:
            self._verify_checksum_if_present(path, raw)

    def _verify_checksum_if_present(self, path: Path, raw: str) -> None:
        checksum_path = _checksum_path(path)
        self._assert_path_within_history(checksum_path)
        if not checksum_path.exists():
            return
        try:
            checksum_text = checksum_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise HistoryCorruptionError(
                f"Persisted history checksum {self._storage_reference(checksum_path)!r} cannot be read"
            ) from exc
        if not _CHECKSUM_PATTERN.fullmatch(checksum_text):
            raise HistoryCorruptionError(
                f"Persisted history checksum {self._storage_reference(checksum_path)!r} is invalid"
            )
        if checksum_text != _checksum_record(raw).strip():
            raise HistoryCorruptionError(
                f"Persisted history artifact {self._storage_reference(path)!r} is invalid: "
                "checksum does not match"
            )

    def _publish_create_only(self, path: Path, content: str) -> bool:
        """Publish complete content atomically without replacing an existing path."""
        self._assert_path_within_history(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._assert_path_within_history(path)
        temp_path = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
        self._assert_path_within_history(temp_path)
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        try:
            handle = os.fdopen(fd, "w", encoding="utf-8", newline="\n")
            fd = -1
            with handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp_path, path)
            except FileExistsError:
                return False
            _fsync_directory(path.parent)
            return True
        finally:
            if fd != -1:
                os.close(fd)
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass

    def _inspect_checksum(
        self,
        path: Path,
        raw: str,
        *,
        artifact_kind: str,
        artifact_id: str,
    ) -> tuple[HistoryStorageIntegrityIssue, ...]:
        checksum_path = _checksum_path(path)
        if not self._path_is_within_history(checksum_path):
            return (
                self._integrity_issue(
                    HistoryIntegrityIssueCode.UNKNOWN_ARTIFACT_LAYOUT,
                    checksum_path,
                    artifact_kind=artifact_kind,
                    artifact_id=artifact_id,
                    detail="resolved checksum path escapes history root",
                ),
            )
        if not checksum_path.is_file():
            return (
                self._integrity_issue(
                    HistoryIntegrityIssueCode.CHECKSUM_MISSING,
                    path,
                    artifact_kind=artifact_kind,
                    artifact_id=artifact_id,
                    detail="artifact has no SHA-256 checksum sidecar",
                ),
            )
        try:
            checksum_text = checksum_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            return (
                self._integrity_issue(
                    HistoryIntegrityIssueCode.CHECKSUM_INVALID,
                    checksum_path,
                    artifact_kind=artifact_kind,
                    artifact_id=artifact_id,
                    detail=f"checksum could not be read: {exc}",
                ),
            )
        if not _CHECKSUM_PATTERN.fullmatch(checksum_text):
            return (
                self._integrity_issue(
                    HistoryIntegrityIssueCode.CHECKSUM_INVALID,
                    checksum_path,
                    artifact_kind=artifact_kind,
                    artifact_id=artifact_id,
                    detail="checksum sidecar is not canonical sha256:<hex>",
                ),
            )
        if checksum_text != _checksum_record(raw).strip():
            return (
                self._integrity_issue(
                    HistoryIntegrityIssueCode.CHECKSUM_MISMATCH,
                    path,
                    artifact_kind=artifact_kind,
                    artifact_id=artifact_id,
                    detail="artifact content does not match its checksum sidecar",
                ),
            )
        return ()

    def _resolve_history_spec(
        self,
        path: Path,
    ) -> tuple[_HistoryKindSpec[BaseModel], str, str | None] | None:
        try:
            relative = path.relative_to(self._history_root)
        except ValueError:
            return None
        parts = relative.parts
        if not parts:
            return None
        spec = _HISTORY_KIND_SPECS.get(parts[0])
        if spec is None:
            return None

        parent_change_set_id: str | None = None
        if spec is _CHANGE_SET_DECISIONS:
            if len(parts) != 3 or not parts[2].endswith(".json"):
                return None
            try:
                parent_change_set_id = _safe_artifact_id(parts[1])
                artifact_id = _safe_artifact_id(parts[2][:-5])
            except (TypeError, ValueError):
                return None
        else:
            if len(parts) != 2 or not parts[1].endswith(".json"):
                return None
            try:
                artifact_id = _safe_artifact_id(parts[1][:-5])
            except (TypeError, ValueError):
                return None
        return spec, artifact_id, parent_change_set_id

    def _integrity_issue(
        self,
        code: HistoryIntegrityIssueCode,
        path: Path,
        *,
        detail: str,
        artifact_kind: str | None = None,
        artifact_id: str | None = None,
    ) -> HistoryStorageIntegrityIssue:
        if artifact_kind is None:
            try:
                artifact_kind = path.relative_to(self._history_root).parts[0]
            except (ValueError, IndexError):
                artifact_kind = "unknown"
        return HistoryStorageIntegrityIssue(
            code=code,
            artifact_kind=artifact_kind,
            artifact_id=artifact_id,
            storage_reference=self._storage_reference(path),
            detail=detail,
        )

    def _storage_reference(self, path: Path) -> str:
        try:
            return path.relative_to(self._repository_root).as_posix()
        except ValueError:
            return path.as_posix()

    def _path_is_within_history(self, path: Path) -> bool:
        try:
            resolved = path.resolve(strict=False)
            return resolved.is_relative_to(
                self._repository_root
            ) and resolved.is_relative_to(self._history_root)
        except OSError:
            return False

    def _assert_path_within_history(self, path: Path) -> None:
        if not self._path_is_within_history(path):
            raise ValueError("history path escapes configured history root")


def _integrity_issue_sort_key(
    issue: HistoryStorageIntegrityIssue,
) -> tuple[str, str, str, str, str]:
    return (
        issue.storage_reference,
        issue.code.value,
        issue.artifact_kind,
        issue.artifact_id or "",
        issue.detail,
    )


def _path_name(path: Path) -> str:
    return path.name


def _canonical_artifact_json(
    spec: _HistoryKindSpec[T],
    artifact: T,
) -> str:
    """Serialize at the persistence boundary, including legacy wire compatibility."""
    if spec.serializer is not None:
        return canonical_compact_json(spec.serializer(artifact))
    return _canonical_model_json(artifact)


def _parse_artifact_json(
    spec: _HistoryKindSpec[T],
    raw: str,
) -> T:
    """Rehydrate persisted wire data through the kind-specific boundary adapter."""
    if spec.parser is not None:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("Persisted history artifact must be a JSON object")
        return spec.parser(payload)
    return spec.model_type.model_validate_json(raw)


def _canonical_model_json(artifact: BaseModel) -> str:
    """Serialize persisted models with aliases so nested ODCS models round-trip."""
    return canonical_compact_json(artifact.model_dump(mode="json", by_alias=True))


def _checksum_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.sha256")


def _checksum_record(raw: str) -> str:
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"sha256:{digest}\n"


def _fsync_directory(path: Path) -> None:
    """Persist directory metadata where the host supports directory fsync."""
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        fd = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _safe_artifact_id(value: str) -> str:
    cleaned = _required_text(value, "artifact_id")
    if not _SAFE_ARTIFACT_ID.fullmatch(cleaned):
        raise ValueError("artifact_id contains characters unsafe for history file names")
    return cleaned


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be str")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty")
    return cleaned
