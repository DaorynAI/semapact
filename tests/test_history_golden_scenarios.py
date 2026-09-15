from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.application.services.deployment_history import DeploymentHistoryService
from semapact.application.services.evolution import EvolutionChainService
from semapact.application.services.governance import GovernanceService
from semapact.application.services.history import ProposalHistoryService
from semapact.application.services.history_integrity import HistoryIntegrityService
from semapact.application.services.release_history import ReleaseHistoryService
from semapact.application.services.runtime_history import RuntimeHistoryService
from semapact.contractops import (
    ReviewAuthorizationEvidence,
    ReviewEvidenceAction,
    VersionAuthorityConfig,
    apply_contract_release,
    authorize_contract_operation,
    build_change_set,
    build_release_plan,
    resolve_release_version,
)
from semapact.deployment import (
    DeploymentAuthorization,
    DeploymentPreview,
    DeploymentTarget,
    authorize_deployment,
    build_deployment_plan,
)
from semapact.deployment.models import compute_deployment_preview_id
from semapact.governance import DecisionResult
from semapact.governance.gate import GovernanceOperation
from semapact.history import DeploymentStatus, HistoryConflictError
from semapact.observation import (
    ObservedAsset,
    ObservedAssetIdentity,
    ObservedPlatformState,
    with_observed_state_fingerprint,
)
from semapact.platforms.git import GitWorkingTreeHistoryRepository
from semapact.reconciliation import (
    ReconciliationDifference,
    ReconciliationDifferenceType,
    ReconciliationResult,
    ReconciliationSubject,
    RuntimeDriftStatus,
    RuntimeReasonCode,
)
from semapact.revision import build_contract_revision


GOLDEN_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "history_golden"
    / "v1"
    / "review_multi_deploy.json"
)
CONTRACT_ID = "orders-product"
CURRENT_VERSION = "1.2.3"
EFFECTIVE_DATE = "2026-09-15"


def _contract(
    *,
    name: str = "Orders",
    version: str = CURRENT_VERSION,
    include_note: bool = False,
) -> OpenDataContractStandard:
    properties = [
        SchemaProperty(
            name="id",
            logicalType="string",
            physicalType="varchar(255)",
            required=True,
        )
    ]
    if include_note:
        properties.append(
            SchemaProperty(
                name="note",
                logicalType="string",
                physicalType="varchar(255)",
                required=False,
            )
        )
    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id=CONTRACT_ID,
        name=name,
        version=version,
        status="active",
        schema=[SchemaObject(name="orders", properties=properties)],
    )


def _proposal_history(backend: GitWorkingTreeHistoryRepository) -> ProposalHistoryService:
    return ProposalHistoryService(
        revisions=backend,
        change_sets=backend,
        decisions=backend,
        decision_links=backend,
    )


def _release_history(backend: GitWorkingTreeHistoryRepository) -> ReleaseHistoryService:
    return ReleaseHistoryService(
        revisions=backend,
        change_sets=backend,
        decisions=backend,
        decision_links=backend,
        release_plans=backend,
        release_records=backend,
    )


def _deployment_history(backend: GitWorkingTreeHistoryRepository) -> DeploymentHistoryService:
    return DeploymentHistoryService(
        releases=backend,
        deployment_plans=backend,
        deployment_previews=backend,
        deployment_authorizations=backend,
        deployment_records=backend,
    )


def _runtime_history(backend: GitWorkingTreeHistoryRepository) -> RuntimeHistoryService:
    return RuntimeHistoryService(
        observations=backend,
        reconciliations=backend,
        releases=backend,
        deployments=backend,
    )


def _evolution(backend: GitWorkingTreeHistoryRepository) -> EvolutionChainService:
    return EvolutionChainService(
        revisions=backend,
        change_sets=backend,
        decisions=backend,
        decision_links=backend,
        releases=backend,
        deployments=backend,
        observations=backend,
        runtime_reconciliations=backend,
    )


def _record_release(
    root: Path,
    *,
    base: OpenDataContractStandard,
    candidate: OpenDataContractStandard,
    source: str,
):
    backend = GitWorkingTreeHistoryRepository(root)
    base_revision = build_contract_revision(base)
    candidate_revision = build_contract_revision(candidate)
    proposal = GovernanceService().evaluate_proposal(
        base_revision.contract,
        candidate_revision.contract,
        effective_date=EFFECTIVE_DATE,
        base_revision_ref=base_revision.revision_id,
        candidate_revision_ref=candidate_revision.revision_id,
        source=source,
        actor_reference="actor:golden",
    )
    _proposal_history(backend).record_proposal(
        proposal,
        base_revision=base_revision,
        candidate_revision=candidate_revision,
    )

    release_plan = build_release_plan(proposal.change_set, proposal.decision)
    version_resolution = resolve_release_version(
        release_plan,
        current_version=CURRENT_VERSION,
        config=VersionAuthorityConfig(),
    )
    evidence = None
    if proposal.decision.decision is DecisionResult.REVIEW:
        evidence = ReviewAuthorizationEvidence(
            evidence_reference="review:apply:golden",
            decision_id=proposal.decision.decision_id,
            change_set_id=proposal.change_set.change_set_id,
            release_plan_id=release_plan.release_plan_id,
            version_resolution_id=version_resolution.version_resolution_id,
            operation=GovernanceOperation.APPLY,
            action=ReviewEvidenceAction.APPROVE,
        )
    authorization = authorize_contract_operation(
        proposal.decision,
        proposal.change_set,
        release_plan,
        version_resolution,
        GovernanceOperation.APPLY,
        evidence=evidence,
    )
    applied_release = apply_contract_release(
        candidate_revision.contract,
        candidate_revision_ref=candidate_revision.revision_id,
        decision=proposal.decision,
        change_set=proposal.change_set,
        release_plan=release_plan,
        version_resolution=version_resolution,
        authorization=authorization,
    )
    release_record = _release_history(backend).record_release(
        release_plan=release_plan,
        version_resolution=version_resolution,
        authorization=authorization,
        applied_release=applied_release,
    )
    return SimpleNamespace(
        backend=backend,
        base_revision=base_revision,
        candidate_revision=candidate_revision,
        proposal=proposal,
        release_plan=release_plan,
        version_resolution=version_resolution,
        authorization=authorization,
        applied_release=applied_release,
        release_record=release_record,
    )


def _deployment_preview(plan, *, label: str) -> DeploymentPreview:
    observation_fingerprint = f"preview-observation:{label}"
    preview_id = compute_deployment_preview_id(
        deployment_plan_id=plan.deployment_plan_id,
        platform=plan.target.platform,
        runtime_target=plan.target.runtime_target,
        source_identifier=plan.target.source_reference,
        observation_fingerprint=observation_fingerprint,
        operations=(),
    )
    return DeploymentPreview(
        deployment_preview_id=preview_id,
        deployment_plan_id=plan.deployment_plan_id,
        platform=plan.target.platform,
        runtime_target=plan.target.runtime_target,
        source_identifier=plan.target.source_reference,
        observation_fingerprint=observation_fingerprint,
        operations=(),
    )


def _record_deployment(
    bundle,
    *,
    label: str,
    runtime_target: str,
    source_reference: str,
    status: DeploymentStatus,
    started_at: datetime,
):
    plan = build_deployment_plan(
        bundle.applied_release,
        DeploymentTarget(
            platform="databricks",
            runtime_target=runtime_target,
            source_reference=source_reference,
            server_name=label,
        ),
    )
    deploy_evidence = ReviewAuthorizationEvidence(
        evidence_reference=f"review:deploy:{label}",
        decision_id=bundle.proposal.decision.decision_id,
        change_set_id=bundle.proposal.change_set.change_set_id,
        release_plan_id=bundle.release_plan.release_plan_id,
        version_resolution_id=bundle.version_resolution.version_resolution_id,
        operation=GovernanceOperation.DEPLOY,
        action=ReviewEvidenceAction.APPROVE,
        scope_reference=plan.deployment_plan_id,
    )
    contractops_authorization = authorize_contract_operation(
        bundle.proposal.decision,
        bundle.proposal.change_set,
        bundle.release_plan,
        bundle.version_resolution,
        GovernanceOperation.DEPLOY,
        evidence=deploy_evidence,
    )
    deployment_authorization: DeploymentAuthorization = authorize_deployment(
        plan,
        bundle.applied_release,
        contractops_authorization,
    )
    preview = _deployment_preview(plan, label=label)
    record = _deployment_history(bundle.backend).record_execution(
        plan=plan,
        preview=preview,
        authorization=deployment_authorization,
        status=status,
        started_at=started_at,
        completed_at=started_at + timedelta(seconds=5),
        actor_reference="agent:golden-deploy",
        external_reference=f"run:{label}",
    )
    return SimpleNamespace(
        plan=plan,
        preview=preview,
        authorization=deployment_authorization,
        record=record,
    )


def _observation(
    *,
    captured_at: datetime,
    source_reference: str,
    namespace: tuple[str, str],
    asset_type: str,
) -> ObservedPlatformState:
    return with_observed_state_fingerprint(
        ObservedPlatformState(
            platform="databricks",
            source_identifier=source_reference,
            assets=(
                ObservedAsset(
                    identity=ObservedAssetIdentity(
                        platform="databricks",
                        namespace=namespace,
                        asset="orders",
                    ),
                    asset_type=asset_type,
                ),
            ),
            captured_at=captured_at,
        )
    )


def _reconciliation_result(
    observation: ObservedPlatformState,
    *,
    version: str,
    drift: bool,
) -> ReconciliationResult:
    differences = ()
    if drift:
        differences = (
            ReconciliationDifference(
                difference_type=ReconciliationDifferenceType.MISMATCH,
                subject=ReconciliationSubject.PHYSICAL_TYPE,
                reason_code=RuntimeReasonCode.RUNTIME_PHYSICAL_TYPE_CHANGED,
                path="orders.id.physical_type",
                asset_identity="orders",
                property_identity="id",
                expected="STRING",
                observed="BIGINT",
            ),
        )
    assert observation.fingerprint is not None
    return ReconciliationResult(
        contract_id=CONTRACT_ID,
        contract_version=version,
        observation_source_identifier=observation.source_identifier,
        observation_fingerprint=observation.fingerprint,
        differences=differences,
    )


def _record_runtime(bundle, deployment, *, captured_at: datetime, drift: bool):
    namespace = tuple(deployment.record.runtime_target.split("."))
    assert len(namespace) == 2
    observation = _observation(
        captured_at=captured_at,
        source_reference=deployment.record.source_reference,
        namespace=(namespace[0], namespace[1]),
        asset_type="VIEW" if drift else "TABLE",
    )
    record = _runtime_history(bundle.backend).record_reconciliation(
        observation,
        _reconciliation_result(
            observation,
            version=bundle.release_record.contract_version,
            drift=drift,
        ),
        release_record_id=bundle.release_record.release_record_id,
        deployment_record_id=deployment.record.deployment_record_id,
    )
    return SimpleNamespace(observation=observation, record=record)


def _evolution_projection(chain) -> dict[str, object]:
    proposals = []
    for proposal in chain.proposals:
        releases = []
        for release in proposal.releases:
            deployments = []
            for deployment in release.deployments:
                deployments.append(
                    {
                        "deploymentRecordId": deployment.deployment.deployment_record_id,
                        "runtimeTarget": deployment.deployment.runtime_target,
                        "status": deployment.deployment.status.value,
                        "runtime": [
                            {
                                "reconciliationRecordId": item.reconciliation.runtime_reconciliation_record_id,
                                "observationRecordId": item.reconciliation.observation_record_id,
                                "status": item.reconciliation.status.value,
                            }
                            for item in deployment.runtime
                        ],
                    }
                )
            releases.append(
                {
                    "releaseRecordId": release.release.release_record_id,
                    "contractVersion": release.release.contract_version,
                    "releasedRevisionId": release.release.released_revision_id,
                    "deployments": deployments,
                }
            )
        proposals.append(
            {
                "changeSetId": proposal.change_set.change_set_id,
                "decisionId": proposal.decision.decision_id if proposal.decision else None,
                "decision": proposal.decision.decision.value if proposal.decision else None,
                "baseRevisionId": (
                    proposal.base_revision.revision_id if proposal.base_revision else None
                ),
                "candidateRevisionId": (
                    proposal.candidate_revision.revision_id
                    if proposal.candidate_revision
                    else None
                ),
                "releases": releases,
            }
        )
    return {
        "contractId": chain.contract_id,
        "proposals": proposals,
        "unlinkedReleaseIds": [
            item.release.release_record_id for item in chain.unlinked_releases
        ],
        "unlinkedRuntimeIds": [
            item.reconciliation.runtime_reconciliation_record_id
            for item in chain.unlinked_runtime
        ],
        "brokenReferences": [
            {
                "sourceKind": item.source_kind,
                "sourceId": item.source_id,
                "referenceField": item.reference_field,
                "targetKind": item.target_kind,
                "targetId": item.target_id,
                "reason": item.reason,
            }
            for item in chain.broken_references
        ],
    }


def _history_files(root: Path) -> dict[str, object]:
    history_root = root / ".semapact" / "history"
    files: dict[str, object] = {}
    for path in sorted(
        (item for item in history_root.rglob("*") if item.is_file()),
        key=Path.as_posix,
    ):
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        files[relative] = json.loads(text) if path.suffix == ".json" else text.strip()
    return files


def _build_review_multi_deploy(root: Path):
    bundle = _record_release(
        root,
        base=_contract(),
        candidate=_contract(include_note=True),
        source="golden-review",
    )
    assert bundle.proposal.decision.decision is DecisionResult.REVIEW

    start = datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc)
    production = _record_deployment(
        bundle,
        label="production",
        runtime_target="main.prod",
        source_reference="workspace:prod",
        status=DeploymentStatus.SUCCEEDED,
        started_at=start,
    )
    staging = _record_deployment(
        bundle,
        label="staging",
        runtime_target="main.stage",
        source_reference="workspace:stage",
        status=DeploymentStatus.FAILED,
        started_at=start + timedelta(minutes=10),
    )
    sync = _record_runtime(
        bundle,
        production,
        captured_at=start + timedelta(hours=1),
        drift=False,
    )
    drift = _record_runtime(
        bundle,
        production,
        captured_at=start + timedelta(hours=2),
        drift=True,
    )
    assert sync.record.status is RuntimeDriftStatus.IN_SYNC
    assert drift.record.status is RuntimeDriftStatus.DRIFT

    reloaded = GitWorkingTreeHistoryRepository(root)
    chain = _evolution(reloaded).reconstruct(CONTRACT_ID)
    assert _evolution(reloaded).reconstruct(CONTRACT_ID) == chain
    integrity = HistoryIntegrityService(
        storage=reloaded,
        evolution=_evolution(reloaded),
    ).check_contract(CONTRACT_ID)
    assert integrity.valid is True

    manifest = {
        "fixtureVersion": "history-v1",
        "files": _history_files(root),
        "evolution": _evolution_projection(chain),
    }
    return SimpleNamespace(
        manifest=manifest,
        backend=reloaded,
        bundle=bundle,
        production=production,
        staging=staging,
        sync=sync,
        drift=drift,
        chain=chain,
    )


def test_review_multi_deploy_history_matches_checked_in_v1_fixture(tmp_path: Path) -> None:
    first = _build_review_multi_deploy(tmp_path / "first")
    second = _build_review_multi_deploy(tmp_path / "second")

    assert first.manifest == second.manifest
    expected = json.loads(GOLDEN_FIXTURE.read_text(encoding="utf-8"))
    if first.manifest != expected:
        pytest.fail(
            "history golden fixture mismatch; update only for an intentional persisted "
            "schema/identity change.\nACTUAL:\n"
            + json.dumps(first.manifest, indent=2, sort_keys=True)
        )


def test_allow_release_reconstructs_without_review_evidence(tmp_path: Path) -> None:
    bundle = _record_release(
        tmp_path,
        base=_contract(name="Orders old"),
        candidate=_contract(name="Orders new"),
        source="golden-allow",
    )

    assert bundle.proposal.decision.decision is DecisionResult.ALLOW
    assert bundle.authorization.evidence_reference is None
    chain = _evolution(GitWorkingTreeHistoryRepository(tmp_path)).reconstruct(CONTRACT_ID)
    assert len(chain.proposals) == 1
    assert chain.proposals[0].decision is not None
    assert chain.proposals[0].decision.decision is DecisionResult.ALLOW
    assert len(chain.proposals[0].releases) == 1
    assert chain.proposals[0].releases[0].release == bundle.release_record


def test_blocked_proposal_persists_without_release(tmp_path: Path) -> None:
    backend = GitWorkingTreeHistoryRepository(tmp_path)
    base_revision = build_contract_revision(_contract(version=CURRENT_VERSION))
    candidate_revision = build_contract_revision(_contract(version="2.0.0"))
    proposal = GovernanceService().evaluate_proposal(
        base_revision.contract,
        candidate_revision.contract,
        effective_date=EFFECTIVE_DATE,
        base_revision_ref=base_revision.revision_id,
        candidate_revision_ref=candidate_revision.revision_id,
        source="golden-block",
        actor_reference="actor:golden",
    )
    assert proposal.decision.decision is DecisionResult.BLOCK
    _proposal_history(backend).record_proposal(
        proposal,
        base_revision=base_revision,
        candidate_revision=candidate_revision,
    )

    chain = _evolution(backend).reconstruct(CONTRACT_ID)
    assert len(chain.proposals) == 1
    assert chain.proposals[0].decision is not None
    assert chain.proposals[0].decision.decision is DecisionResult.BLOCK
    assert chain.proposals[0].releases == ()
    assert backend.list_release_records(CONTRACT_ID) == ()


def test_golden_history_rejects_conflicting_overwrite(tmp_path: Path) -> None:
    scenario = _build_review_multi_deploy(tmp_path)
    decision = scenario.bundle.proposal.decision
    conflicting = decision.model_copy(update={"contract_id": "other-contract"})

    with pytest.raises(HistoryConflictError, match="different content"):
        scenario.backend.put_decision(conflicting)

    assert scenario.backend.get_decision(decision.decision_id) == decision


def test_broken_reference_is_explicit_and_does_not_fabricate_release(tmp_path: Path) -> None:
    bundle = _record_release(
        tmp_path,
        base=_contract(),
        candidate=_contract(include_note=True),
        source="golden-broken-base",
    )
    broken = build_change_set(
        contract_id=CONTRACT_ID,
        base_revision_ref="missing-revision",
        candidate_revision_ref=bundle.candidate_revision.revision_id,
        changes=bundle.proposal.change_set.changes,
        context=bundle.proposal.change_set.context,
        source="golden-broken",
    )
    bundle.backend.put_change_set(broken)

    chain = _evolution(bundle.backend).reconstruct(CONTRACT_ID)
    broken_path = next(item for item in chain.proposals if item.change_set == broken)
    assert broken_path.base_revision is None
    assert broken_path.decision is None
    assert broken_path.releases == ()
    assert any(
        item.source_id == broken.change_set_id
        and item.reference_field == "base_revision_ref"
        and item.target_id == "missing-revision"
        and item.reason == "NOT_FOUND"
        for item in chain.broken_references
    )
