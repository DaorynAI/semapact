"""Read-only reconstruction of persisted governance evolution history."""

from __future__ import annotations

from semapact.application.models.evolution import (
    BrokenHistoryReference,
    ContractEvolution,
    DeploymentEvolution,
    ProposalEvolution,
    ReleaseEvolution,
    RuntimeEvolution,
)
from semapact.contractops import ChangeSet
from semapact.governance import GovernanceDecision
from semapact.history import (
    ChangeSetDecisionLinkHistoryRepository,
    ChangeSetHistoryRepository,
    ContractRevisionHistoryRepository,
    DecisionHistoryRepository,
    DeploymentRecordHistoryRepository,
    HistoryNotFoundError,
    ReleaseRecord,
    ReleaseRecordHistoryRepository,
    RuntimeObservationHistoryRepository,
    RuntimeReconciliationHistoryRepository,
    RuntimeReconciliationRecord,
)
from semapact.revision import ContractRevision


class EvolutionChainService:
    """Reconstruct one contract's history from existing stable artifact references."""

    def __init__(
        self,
        *,
        revisions: ContractRevisionHistoryRepository,
        change_sets: ChangeSetHistoryRepository,
        decisions: DecisionHistoryRepository,
        decision_links: ChangeSetDecisionLinkHistoryRepository,
        releases: ReleaseRecordHistoryRepository,
        deployments: DeploymentRecordHistoryRepository,
        observations: RuntimeObservationHistoryRepository,
        runtime_reconciliations: RuntimeReconciliationHistoryRepository,
    ) -> None:
        self._revisions = revisions
        self._change_sets = change_sets
        self._decisions = decisions
        self._decision_links = decision_links
        self._releases = releases
        self._deployments = deployments
        self._observations = observations
        self._runtime_reconciliations = runtime_reconciliations

    def reconstruct(self, contract_id: str) -> ContractEvolution:
        """Return a deterministic read model without persisting a second history graph."""
        contract_id = _required_text(contract_id, "contract_id")
        issues: list[BrokenHistoryReference] = []

        change_sets = tuple(
            sorted(
                self._change_sets.list_change_sets(contract_id),
                key=lambda item: item.change_set_id,
            )
        )
        release_records = tuple(
            sorted(
                self._releases.list_release_records(contract_id),
                key=lambda item: item.release_record_id,
            )
        )
        runtime_records = tuple(
            sorted(
                self._runtime_reconciliations.list_runtime_reconciliation_records(
                    contract_id
                ),
                key=lambda item: item.runtime_reconciliation_record_id,
            )
        )

        runtime_by_id = {
            record.runtime_reconciliation_record_id: self._runtime_evolution(
                record,
                issues,
            )
            for record in runtime_records
        }
        runtime_by_release: dict[str, list[RuntimeReconciliationRecord]] = {}
        runtime_by_deployment: dict[str, list[RuntimeReconciliationRecord]] = {}
        for record in runtime_records:
            if record.deployment_record_id is not None:
                runtime_by_deployment.setdefault(record.deployment_record_id, []).append(record)
            elif record.release_record_id is not None:
                runtime_by_release.setdefault(record.release_record_id, []).append(record)

        releases_by_path: dict[tuple[str, str], list[ReleaseRecord]] = {}
        for release in release_records:
            releases_by_path.setdefault(
                (release.change_set_id, release.decision_id),
                [],
            ).append(release)

        consumed_release_ids: set[str] = set()
        consumed_runtime_ids: set[str] = set()
        known_deployment_ids: set[str] = set()
        linked_decision_pairs: set[tuple[str, str]] = set()
        proposals: list[ProposalEvolution] = []

        for change_set in change_sets:
            base_revision = self._resolve_revision(
                change_set,
                field_name="base_revision_ref",
                revision_id=change_set.base_revision_ref,
                contract_id=contract_id,
                issues=issues,
            )
            candidate_revision = self._resolve_revision(
                change_set,
                field_name="candidate_revision_ref",
                revision_id=change_set.candidate_revision_ref,
                contract_id=contract_id,
                issues=issues,
            )
            links = tuple(
                sorted(
                    self._decision_links.list_change_set_decision_links(
                        change_set.change_set_id
                    ),
                    key=lambda item: item.decision_id,
                )
            )
            if not links:
                proposals.append(
                    ProposalEvolution(
                        change_set=change_set,
                        base_revision=base_revision,
                        candidate_revision=candidate_revision,
                        decision=None,
                    )
                )
                continue

            for link in links:
                pair = (change_set.change_set_id, link.decision_id)
                linked_decision_pairs.add(pair)
                decision = self._resolve_decision(
                    change_set,
                    link.decision_id,
                    contract_id=contract_id,
                    issues=issues,
                )
                releases = tuple(
                    self._build_release(
                        release,
                        contract_id=contract_id,
                        runtime_by_id=runtime_by_id,
                        runtime_by_release=runtime_by_release,
                        runtime_by_deployment=runtime_by_deployment,
                        consumed_runtime_ids=consumed_runtime_ids,
                        known_deployment_ids=known_deployment_ids,
                        issues=issues,
                    )
                    for release in sorted(
                        releases_by_path.get(pair, ()),
                        key=lambda item: item.release_record_id,
                    )
                )
                consumed_release_ids.update(
                    item.release.release_record_id for item in releases
                )
                proposals.append(
                    ProposalEvolution(
                        change_set=change_set,
                        base_revision=base_revision,
                        candidate_revision=candidate_revision,
                        decision=decision,
                        releases=releases,
                    )
                )

        change_set_ids = {item.change_set_id for item in change_sets}
        unlinked_releases: list[ReleaseEvolution] = []
        for release in release_records:
            if release.release_record_id in consumed_release_ids:
                continue
            pair = (release.change_set_id, release.decision_id)
            if release.change_set_id not in change_set_ids:
                _add_issue(
                    issues,
                    source_kind="ReleaseRecord",
                    source_id=release.release_record_id,
                    reference_field="change_set_id",
                    target_kind="ChangeSet",
                    target_id=release.change_set_id,
                    reason="NOT_FOUND",
                )
            elif pair not in linked_decision_pairs:
                _add_issue(
                    issues,
                    source_kind="ReleaseRecord",
                    source_id=release.release_record_id,
                    reference_field="decision_id",
                    target_kind="ChangeSetDecisionLink",
                    target_id=f"{release.change_set_id}:{release.decision_id}",
                    reason="RELATION_MISSING",
                )
            unlinked_releases.append(
                self._build_release(
                    release,
                    contract_id=contract_id,
                    runtime_by_id=runtime_by_id,
                    runtime_by_release=runtime_by_release,
                    runtime_by_deployment=runtime_by_deployment,
                    consumed_runtime_ids=consumed_runtime_ids,
                    known_deployment_ids=known_deployment_ids,
                    issues=issues,
                )
            )

        release_ids = {item.release_record_id for item in release_records}
        unlinked_runtime: list[RuntimeEvolution] = []
        for record in runtime_records:
            record_id = record.runtime_reconciliation_record_id
            if record_id in consumed_runtime_ids:
                continue
            if (
                record.release_record_id is not None
                and record.release_record_id not in release_ids
            ):
                _add_issue(
                    issues,
                    source_kind="RuntimeReconciliationRecord",
                    source_id=record_id,
                    reference_field="release_record_id",
                    target_kind="ReleaseRecord",
                    target_id=record.release_record_id,
                    reason="NOT_FOUND",
                )
            if (
                record.deployment_record_id is not None
                and record.deployment_record_id not in known_deployment_ids
            ):
                _add_issue(
                    issues,
                    source_kind="RuntimeReconciliationRecord",
                    source_id=record_id,
                    reference_field="deployment_record_id",
                    target_kind="DeploymentRecord",
                    target_id=record.deployment_record_id,
                    reason="NOT_FOUND",
                )
            unlinked_runtime.append(runtime_by_id[record_id])

        proposals.sort(
            key=lambda item: (
                item.change_set.change_set_id,
                item.decision.decision_id if item.decision is not None else "",
            )
        )
        unlinked_releases.sort(key=lambda item: item.release.release_record_id)
        unlinked_runtime.sort(
            key=lambda item: item.reconciliation.runtime_reconciliation_record_id
        )
        issues.sort(
            key=lambda item: (
                item.source_kind,
                item.source_id,
                item.reference_field,
                item.target_kind,
                item.target_id,
                item.reason,
            )
        )
        return ContractEvolution(
            contract_id=contract_id,
            proposals=tuple(proposals),
            unlinked_releases=tuple(unlinked_releases),
            unlinked_runtime=tuple(unlinked_runtime),
            broken_references=tuple(issues),
        )

    def _resolve_revision(
        self,
        change_set: ChangeSet,
        *,
        field_name: str,
        revision_id: str,
        contract_id: str,
        issues: list[BrokenHistoryReference],
    ) -> ContractRevision | None:
        try:
            revision = self._revisions.get_revision(revision_id)
        except HistoryNotFoundError:
            _add_issue(
                issues,
                source_kind="ChangeSet",
                source_id=change_set.change_set_id,
                reference_field=field_name,
                target_kind="ContractRevision",
                target_id=revision_id,
                reason="NOT_FOUND",
            )
            return None
        if str(revision.contract.id or "") != contract_id:
            _add_issue(
                issues,
                source_kind="ChangeSet",
                source_id=change_set.change_set_id,
                reference_field=field_name,
                target_kind="ContractRevision",
                target_id=revision_id,
                reason="CONTRACT_MISMATCH",
            )
            return None
        return revision

    def _resolve_decision(
        self,
        change_set: ChangeSet,
        decision_id: str,
        *,
        contract_id: str,
        issues: list[BrokenHistoryReference],
    ) -> GovernanceDecision | None:
        try:
            decision = self._decisions.get_decision(decision_id)
        except HistoryNotFoundError:
            _add_issue(
                issues,
                source_kind="ChangeSetDecisionLink",
                source_id=f"{change_set.change_set_id}:{decision_id}",
                reference_field="decision_id",
                target_kind="GovernanceDecision",
                target_id=decision_id,
                reason="NOT_FOUND",
            )
            return None
        if decision.contract_id != contract_id:
            _add_issue(
                issues,
                source_kind="ChangeSetDecisionLink",
                source_id=f"{change_set.change_set_id}:{decision_id}",
                reference_field="decision_id",
                target_kind="GovernanceDecision",
                target_id=decision_id,
                reason="CONTRACT_MISMATCH",
            )
            return None
        return decision

    def _build_release(
        self,
        release: ReleaseRecord,
        *,
        contract_id: str,
        runtime_by_id: dict[str, RuntimeEvolution],
        runtime_by_release: dict[str, list[RuntimeReconciliationRecord]],
        runtime_by_deployment: dict[str, list[RuntimeReconciliationRecord]],
        consumed_runtime_ids: set[str],
        known_deployment_ids: set[str],
        issues: list[BrokenHistoryReference],
    ) -> ReleaseEvolution:
        released_revision: ContractRevision | None
        try:
            released_revision = self._revisions.get_revision(release.released_revision_id)
        except HistoryNotFoundError:
            released_revision = None
            _add_issue(
                issues,
                source_kind="ReleaseRecord",
                source_id=release.release_record_id,
                reference_field="released_revision_id",
                target_kind="ContractRevision",
                target_id=release.released_revision_id,
                reason="NOT_FOUND",
            )
        else:
            if (
                str(released_revision.contract.id or "") != contract_id
                or str(released_revision.contract.version or "") != release.contract_version
            ):
                _add_issue(
                    issues,
                    source_kind="ReleaseRecord",
                    source_id=release.release_record_id,
                    reference_field="released_revision_id",
                    target_kind="ContractRevision",
                    target_id=release.released_revision_id,
                    reason="RELEASE_MISMATCH",
                )
                released_revision = None

        deployments = tuple(
            sorted(
                self._deployments.list_deployment_records_for_release(
                    release.release_record_id
                ),
                key=lambda item: item.deployment_record_id,
            )
        )
        deployment_paths: list[DeploymentEvolution] = []
        for deployment in deployments:
            known_deployment_ids.add(deployment.deployment_record_id)
            linked_runtime: list[RuntimeEvolution] = []
            for record in sorted(
                runtime_by_deployment.get(deployment.deployment_record_id, ()),
                key=lambda item: item.runtime_reconciliation_record_id,
            ):
                if record.release_record_id != release.release_record_id:
                    _add_issue(
                        issues,
                        source_kind="RuntimeReconciliationRecord",
                        source_id=record.runtime_reconciliation_record_id,
                        reference_field="release_record_id",
                        target_kind="ReleaseRecord",
                        target_id=str(record.release_record_id or ""),
                        reason="DEPLOYMENT_RELEASE_MISMATCH",
                    )
                    continue
                linked_runtime.append(runtime_by_id[record.runtime_reconciliation_record_id])
                consumed_runtime_ids.add(record.runtime_reconciliation_record_id)
            deployment_paths.append(
                DeploymentEvolution(
                    deployment=deployment,
                    runtime=tuple(linked_runtime),
                )
            )

        release_runtime = tuple(
            runtime_by_id[record.runtime_reconciliation_record_id]
            for record in sorted(
                runtime_by_release.get(release.release_record_id, ()),
                key=lambda item: item.runtime_reconciliation_record_id,
            )
        )
        consumed_runtime_ids.update(
            item.reconciliation.runtime_reconciliation_record_id for item in release_runtime
        )
        return ReleaseEvolution(
            release=release,
            released_revision=released_revision,
            deployments=tuple(deployment_paths),
            runtime=release_runtime,
        )

    def _runtime_evolution(
        self,
        record: RuntimeReconciliationRecord,
        issues: list[BrokenHistoryReference],
    ) -> RuntimeEvolution:
        try:
            observation = self._observations.get_runtime_observation_record(
                record.observation_record_id
            )
        except HistoryNotFoundError:
            _add_issue(
                issues,
                source_kind="RuntimeReconciliationRecord",
                source_id=record.runtime_reconciliation_record_id,
                reference_field="observation_record_id",
                target_kind="RuntimeObservationRecord",
                target_id=record.observation_record_id,
                reason="NOT_FOUND",
            )
            return RuntimeEvolution(reconciliation=record, observation=None)

        observed = observation.observation
        if (
            observed.source_identifier != record.result.observation_source_identifier
            or observed.fingerprint != record.result.observation_fingerprint
        ):
            _add_issue(
                issues,
                source_kind="RuntimeReconciliationRecord",
                source_id=record.runtime_reconciliation_record_id,
                reference_field="observation_record_id",
                target_kind="RuntimeObservationRecord",
                target_id=record.observation_record_id,
                reason="EVIDENCE_MISMATCH",
            )
        return RuntimeEvolution(reconciliation=record, observation=observation)


def _add_issue(
    issues: list[BrokenHistoryReference],
    *,
    source_kind: str,
    source_id: str,
    reference_field: str,
    target_kind: str,
    target_id: str,
    reason: str,
) -> None:
    issues.append(
        BrokenHistoryReference(
            source_kind=source_kind,
            source_id=source_id,
            reference_field=reference_field,
            target_kind=target_kind,
            target_id=target_id,
            reason=reason,
        )
    )


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be str")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty")
    return cleaned
