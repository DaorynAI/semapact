"""Read-only reconstruction of canonical governance history."""

from __future__ import annotations

from semapact.application.models.evolution import (
    BrokenHistoryReference,
    ContractEvolution,
    ProposalEvolution,
    ReleaseEvolution,
)
from semapact.contractops import ChangeSet, ContractRelease
from semapact.governance import GovernanceDecision
from semapact.history import (
    ChangeSetDecisionLinkHistoryRepository,
    ChangeSetHistoryRepository,
    ContractReleaseHistoryRepository,
    ContractRevisionHistoryRepository,
    DecisionHistoryRepository,
    HistoryNotFoundError,
)
from semapact.revision import ContractRevision


class EvolutionChainService:
    """Reconstruct proposal → decision → ContractRelease governance history."""

    def __init__(
        self,
        *,
        revisions: ContractRevisionHistoryRepository,
        change_sets: ChangeSetHistoryRepository,
        decisions: DecisionHistoryRepository,
        decision_links: ChangeSetDecisionLinkHistoryRepository,
        releases: ContractReleaseHistoryRepository,
    ) -> None:
        self._revisions = revisions
        self._change_sets = change_sets
        self._decisions = decisions
        self._decision_links = decision_links
        self._releases = releases

    def reconstruct(self, contract_id: str) -> ContractEvolution:
        contract_id = _required_text(contract_id, "contract_id")
        issues: list[BrokenHistoryReference] = []

        change_sets = tuple(
            sorted(
                self._change_sets.list_change_sets(contract_id),
                key=lambda item: item.change_set_id,
            )
        )
        releases = tuple(
            sorted(
                self._releases.list_contract_releases(contract_id),
                key=lambda item: item.contract_release_id,
            )
        )
        releases_by_path: dict[tuple[str, str], list[ContractRelease]] = {}
        for release in releases:
            releases_by_path.setdefault(
                (release.change_set_id, release.decision_id),
                [],
            ).append(release)

        consumed_release_ids: set[str] = set()
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
                linked_releases = tuple(
                    ReleaseEvolution(release=release)
                    for release in sorted(
                        releases_by_path.get(pair, ()),
                        key=lambda item: item.contract_release_id,
                    )
                )
                consumed_release_ids.update(
                    item.release.contract_release_id for item in linked_releases
                )
                proposals.append(
                    ProposalEvolution(
                        change_set=change_set,
                        base_revision=base_revision,
                        candidate_revision=candidate_revision,
                        decision=decision,
                        releases=linked_releases,
                    )
                )

        change_set_ids = {item.change_set_id for item in change_sets}
        unlinked_releases: list[ReleaseEvolution] = []
        for release in releases:
            if release.contract_release_id in consumed_release_ids:
                continue
            pair = (release.change_set_id, release.decision_id)
            if release.change_set_id not in change_set_ids:
                _add_issue(
                    issues,
                    source_kind="ContractRelease",
                    source_id=release.contract_release_id,
                    reference_field="change_set_id",
                    target_kind="ChangeSet",
                    target_id=release.change_set_id,
                    reason="NOT_FOUND",
                )
            elif pair not in linked_decision_pairs:
                _add_issue(
                    issues,
                    source_kind="ContractRelease",
                    source_id=release.contract_release_id,
                    reference_field="decision_id",
                    target_kind="ChangeSetDecisionLink",
                    target_id=f"{release.change_set_id}:{release.decision_id}",
                    reason="RELATION_MISSING",
                )
            unlinked_releases.append(ReleaseEvolution(release=release))

        proposals.sort(
            key=lambda item: (
                item.change_set.change_set_id,
                item.decision.decision_id if item.decision is not None else "",
            )
        )
        unlinked_releases.sort(key=lambda item: item.release.contract_release_id)
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
