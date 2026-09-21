from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.application.services.evolution import EvolutionChainService
from semapact.application.services.history_integrity import HistoryIntegrityService
from semapact.change_context import ChangeContext
from semapact.contractops import build_change_set_from_decision
from semapact.governance import GovernanceDecision, evaluate_governance_decision
from semapact.history import (
    ChangeSetDecisionLink,
    HistoryConflictError,
    HistoryCorruptionError,
    HistoryIntegrityIssueCode,
)
from semapact.platforms.git import GitWorkingTreeHistoryRepository


CONTEXT = ChangeContext(effective_date=date(2026, 9, 15))


def _contract(*, name: str) -> OpenDataContractStandard:
    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="orders-product",
        name=name,
        version="1.0.0",
        status="active",
        schema=[
            SchemaObject(
                name="orders",
                properties=[
                    SchemaProperty(
                        name="id",
                        logicalType="string",
                        physicalType="varchar(255)",
                        required=True,
                    )
                ],
            )
        ],
    )


def _decision() -> GovernanceDecision:
    return evaluate_governance_decision(
        _contract(name="orders-base"),
        _contract(name="orders-candidate"),
        context=CONTEXT,
    )


def _decision_path(tmp_path: Path, decision: GovernanceDecision) -> Path:
    return (
        tmp_path
        / ".semapact"
        / "history"
        / "decisions"
        / f"{decision.decision_id}.json"
    )


def _evolution_service(backend: GitWorkingTreeHistoryRepository) -> EvolutionChainService:
    return EvolutionChainService(
        revisions=backend,
        change_sets=backend,
        decisions=backend,
        decision_links=backend,
        releases=backend,
    )


def test_new_history_write_is_checksum_sealed_and_clean(tmp_path: Path) -> None:
    repository = GitWorkingTreeHistoryRepository(tmp_path)
    decision = _decision()

    repository.put_decision(decision)

    artifact_path = _decision_path(tmp_path, decision)
    checksum_path = artifact_path.with_name(f"{artifact_path.name}.sha256")
    assert artifact_path.is_file()
    assert checksum_path.is_file()
    assert checksum_path.read_text(encoding="utf-8").startswith("sha256:")
    assert repository.get_decision(decision.decision_id) == decision
    assert repository.inspect_history_integrity() == ()


def test_checksum_sealed_tamper_fails_closed_on_read_and_scan(tmp_path: Path) -> None:
    repository = GitWorkingTreeHistoryRepository(tmp_path)
    decision = _decision()
    repository.put_decision(decision)
    artifact_path = _decision_path(tmp_path, decision)
    artifact_path.write_text(
        artifact_path.read_text(encoding="utf-8").replace(
            "orders-product",
            "tampered-product",
        ),
        encoding="utf-8",
    )

    with pytest.raises(HistoryCorruptionError, match="checksum"):
        repository.get_decision(decision.decision_id)

    issues = repository.inspect_history_integrity()
    assert HistoryIntegrityIssueCode.CHECKSUM_MISMATCH in {item.code for item in issues}


def test_idempotent_rewrite_can_seal_pre_checksum_history(tmp_path: Path) -> None:
    repository = GitWorkingTreeHistoryRepository(tmp_path)
    decision = _decision()
    repository.put_decision(decision)
    artifact_path = _decision_path(tmp_path, decision)
    checksum_path = artifact_path.with_name(f"{artifact_path.name}.sha256")
    checksum_path.unlink()

    issues = repository.inspect_history_integrity()
    assert [item.code for item in issues] == [HistoryIntegrityIssueCode.CHECKSUM_MISSING]

    repository.put_decision(decision)

    assert checksum_path.is_file()
    assert repository.inspect_history_integrity() == ()


def test_orphan_checksum_is_reported(tmp_path: Path) -> None:
    repository = GitWorkingTreeHistoryRepository(tmp_path)
    checksum_path = (
        tmp_path
        / ".semapact"
        / "history"
        / "decisions"
        / "orphan.json.sha256"
    )
    checksum_path.parent.mkdir(parents=True)
    checksum_path.write_text("sha256:" + "0" * 64 + "\n", encoding="utf-8")

    issues = repository.inspect_history_integrity()

    assert len(issues) == 1
    assert issues[0].code is HistoryIntegrityIssueCode.ORPHAN_CHECKSUM


def test_conflicting_content_remains_immutable_with_checksum_seal(tmp_path: Path) -> None:
    repository = GitWorkingTreeHistoryRepository(tmp_path)
    decision = _decision()
    repository.put_decision(decision)
    conflicting = decision.model_copy(update={"contract_id": "different-contract"})

    with pytest.raises(HistoryConflictError, match="different content"):
        repository.put_decision(conflicting)


def test_history_state_directory_cannot_escape_repository_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="repository-relative"):
        GitWorkingTreeHistoryRepository(tmp_path, state_directory=tmp_path / "outside")

    with pytest.raises(ValueError, match="must not contain"):
        GitWorkingTreeHistoryRepository(tmp_path, state_directory="../outside")

    with pytest.raises(ValueError, match="must not contain"):
        GitWorkingTreeHistoryRepository(
            tmp_path,
            state_directory="safe/../.semapact/history",
        )


def test_symlink_path_escape_is_rejected(tmp_path: Path) -> None:
    history_root = tmp_path / ".semapact" / "history"
    history_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    decisions = history_root / "decisions"
    try:
        decisions.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("host does not permit symlink creation")

    repository = GitWorkingTreeHistoryRepository(tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        repository.put_decision(_decision())


def test_history_root_replaced_by_symlink_after_init_is_rejected(tmp_path: Path) -> None:
    repository = GitWorkingTreeHistoryRepository(tmp_path)
    history_root = tmp_path / ".semapact" / "history"
    history_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    history_root.rmdir()
    try:
        history_root.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("host does not permit symlink creation")

    with pytest.raises(ValueError, match="escapes"):
        repository.put_decision(_decision())


def test_integrity_service_reuses_evolution_broken_reference_diagnostics(
    tmp_path: Path,
) -> None:
    backend = GitWorkingTreeHistoryRepository(tmp_path)
    decision = _decision()
    change_set = build_change_set_from_decision(
        decision,
        base_revision_ref="missing-base-revision",
        candidate_revision_ref="missing-candidate-revision",
    )
    backend.put_decision(decision)
    backend.put_change_set(change_set)
    backend.put_change_set_decision_link(
        ChangeSetDecisionLink(
            change_set_id=change_set.change_set_id,
            decision_id=decision.decision_id,
        )
    )
    service = HistoryIntegrityService(
        storage=backend,
        evolution=_evolution_service(backend),
    )

    report = service.check_contract("orders-product")

    assert report.storage_issues == ()
    assert report.references_checked is True
    assert report.valid is False
    assert {item.reference_field for item in report.broken_references} == {
        "base_revision_ref",
        "candidate_revision_ref",
    }


def test_integrity_service_stops_reference_traversal_on_storage_corruption(
    tmp_path: Path,
) -> None:
    backend = GitWorkingTreeHistoryRepository(tmp_path)
    decision = _decision()
    backend.put_decision(decision)
    artifact_path = _decision_path(tmp_path, decision)
    artifact_path.write_text("{}", encoding="utf-8")
    service = HistoryIntegrityService(
        storage=backend,
        evolution=_evolution_service(backend),
    )

    report = service.check_contract("orders-product")

    assert report.storage_issues
    assert report.references_checked is False
    assert report.broken_references == ()
    assert report.valid is False
