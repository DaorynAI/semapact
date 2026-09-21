import argparse
import json
from pathlib import Path
from typing import Any

from semapact.application.services.governance import GovernanceService
from semapact.application.services.release_planning import ReleasePlanningService
from semapact.interfaces.commands.utils import (
    _build_git_config,
    _get_repo_path,
)



def run_release_assess(args: argparse.Namespace) -> dict[str, Any]:
    """Build one immutable target-neutral ReleaseBundle."""
    from semapact.application.services.release_workflow import ReleaseWorkflowService
    from semapact.core.loader import ContractLoader

    loader = ContractLoader(runtime_context=args.runtime_context)
    base_contract = loader.load(args.base)
    candidate_contract = loader.load(args.candidate)
    bundle = ReleaseWorkflowService().assess(
        base_contract,
        candidate_contract,
        base_revision_ref=args.base_revision_ref,
        candidate_revision_ref=args.candidate_revision_ref,
        authority_reference=args.authority_reference,
    )
    if args.bundle_out:
        _write_model_artifact(args.bundle_out, bundle)
    return bundle.model_dump(mode="json")


def run_release_approve(args: argparse.Namespace) -> dict[str, Any]:
    """Record explicit REVIEW approval for one exact ReleaseBundle."""
    from semapact.application.models.release import ReleaseBundle
    from semapact.application.services.release_workflow import ReleaseWorkflowService
    from semapact.interfaces.parsing import parse_iso_timestamp
    from semapact.platforms.git import GitWorkingTreeHistoryRepository

    bundle = _load_model(args.bundle, ReleaseBundle)
    approval = ReleaseWorkflowService().approve(
        bundle,
        actor_reference=args.actor_reference,
        recorded_at=parse_iso_timestamp(args.recorded_at),
        comment=args.comment,
    )
    GitWorkingTreeHistoryRepository(args.repository_root).put_approval_record(approval)
    if args.approval_out:
        _write_model_artifact(args.approval_out, approval)
    return approval.model_dump(mode="json")


def run_release_finalize(args: argparse.Namespace) -> dict[str, Any]:
    """Finalize one exact release, persist ledger fact, and materialize versioned ODCS."""
    from semapact.application.models.release import ReleaseBundle
    from semapact.application.services.release_approval import ReleaseApprovalResolver
    from semapact.application.services.release_workflow import ReleaseFinalizer
    from semapact.governance import DecisionResult
    from semapact.platforms.git import GitWorkingTreeHistoryRepository
    from semapact.utils.yaml_utils import dump_yaml

    from semapact.approval import ApprovalRecord

    bundle = _load_model(args.bundle, ReleaseBundle)
    repository = GitWorkingTreeHistoryRepository(args.repository_root)
    approval = None
    resolver = ReleaseApprovalResolver(repository)
    approval_path = getattr(args, "approval", None)
    if approval_path:
        approval = _load_model(approval_path, ApprovalRecord)
        if resolver.has_conflict(bundle):
            from semapact.exceptions import ValidationError

            raise ValidationError(
                "Persisted release approval history contains conflicting exact review evidence"
            )
    elif bundle.decision.decision is DecisionResult.REVIEW:
        approval = resolver.resolve(bundle)

    record = ReleaseFinalizer().finalize(
        bundle,
        approval=approval,
    )
    repository.put_contract_release(record)
    output_path = dump_yaml(bundle.release_snapshot.to_contract(), args.output_contract)
    release_out = getattr(args, "release_out", None)
    if release_out:
        _write_model_artifact(release_out, record)
    return {
        "contractReleaseId": record.contract_release_id,
        "contractId": record.contract_id,
        "contractVersion": record.contract_version,
        "sourceRevisionRef": record.source_revision_ref,
        "releaseBundleDigest": bundle.bundle_digest,
        "outputContract": str(output_path),
        "releaseArtifact": release_out,
    }


def _load_model(path: str, model_type):
    from pydantic import ValidationError as PydanticValidationError

    from semapact.exceptions import ValidationError

    try:
        return model_type.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except (OSError, PydanticValidationError) as exc:
        raise ValidationError(
            f"Invalid {model_type.__name__} artifact '{path}': {exc}"
        ) from exc


def _write_model_artifact(path: str, model) -> None:
    artifact_path = Path(path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(
            model.model_dump(mode="json"),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

def run_release_classify(args: argparse.Namespace) -> dict[str, Any]:
    """Analyze one change without creating canonical release artifacts."""
    from dataclasses import asdict

    from semapact.core.loader import ContractLoader
    from semapact.governance import GovernanceOperation, evaluate_governance_gate
    from semapact.versioning import increment_version

    loader = ContractLoader(runtime_context=args.runtime_context)
    base_contract = loader.load(args.base)
    candidate_contract = loader.load(args.candidate)

    decision = GovernanceService().evaluate(
        base_contract,
        candidate_contract,
    )
    evaluate_governance_gate(decision, GovernanceOperation.ANALYZE)

    current_version = str(base_contract.version or "")
    required_bump = decision.required_version_bump
    breaking_list = [asdict(bc) for bc in decision.policy.breaking_changes]
    reasons_list = [r.message for r in decision.reasons] or ["No contract changes detected"]

    if decision.evidence.has_changes and required_bump in {"minor", "major"}:
        suggested_next_version = increment_version(current_version, required_bump)
    else:
        suggested_next_version = current_version

    return {
        "contractId": str(base_contract.id or ""),
        "currentVersion": current_version,
        "candidateVersion": str(candidate_contract.version or ""),
        "hasChanges": decision.evidence.has_changes,
        "requiredBump": required_bump,
        "suggestedNextVersion": suggested_next_version,
        "reasons": reasons_list,
        "breakingChanges": breaking_list,
        "governanceDecision": decision.model_dump(mode="json"),
    }


def run_release_plan(args: argparse.Namespace) -> dict[str, Any]:
    """Produce exact canonical M2 planning artifacts from one governance pass."""
    from semapact.core.loader import ContractLoader

    loader = ContractLoader(runtime_context=args.runtime_context)
    base_contract = loader.load(args.base)
    candidate_contract = loader.load(args.candidate)

    result = ReleasePlanningService().plan(
        base_contract,
        candidate_contract,
        base_revision_ref=args.base_revision_ref,
        candidate_revision_ref=args.candidate_revision_ref,
        authority_reference=args.authority_reference,
    )
    return {
        "governanceDecision": result.decision.model_dump(mode="json"),
        "changeSet": result.change_set.model_dump(mode="json"),
        "releasePlan": result.release_plan.model_dump(mode="json"),
        "versionResolution": result.version_resolution.model_dump(mode="json"),
    }



def run_release_classify_repo(args: argparse.Namespace) -> dict[str, Any]:
    from semapact.application.services.repository_classification import (
        classify_contracts_in_repo,
        repository_change_to_dict,
    )

    results = classify_contracts_in_repo(
        base_root=args.base_root,
        candidate_root=args.candidate_root,
    )
    return {"contracts": [repository_change_to_dict(item) for item in results]}

