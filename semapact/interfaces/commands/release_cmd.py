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
        effective_date=args.effective_date,
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
    from semapact.application.services.release_workflow import ReleaseWorkflowService
    from semapact.governance import DecisionResult
    from semapact.platforms.git import GitWorkingTreeHistoryRepository
    from semapact.utils.yaml_utils import dump_yaml

    bundle = _load_model(args.bundle, ReleaseBundle)
    repository = GitWorkingTreeHistoryRepository(args.repository_root)
    approval = None
    if bundle.decision.decision is DecisionResult.REVIEW:
        approval = ReleaseApprovalResolver(repository).resolve(bundle)

    record = ReleaseWorkflowService().finalize(
        bundle,
        release_history=repository,
        approval=approval,
    )
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
        effective_date=args.effective_date,
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
        effective_date=args.effective_date,
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


def run_release_prepare(args: argparse.Namespace) -> dict[str, Any]:
    """Compatibility release-tag helper retained for existing Git workflows."""
    from dataclasses import asdict

    from semapact.core.loader import ContractLoader
    from semapact.core.release import apply_release_candidate
    from semapact.governance import GovernanceOperation, enforce_governance_gate
    from semapact.utils.schema_utils import contract_to_dict
    from semapact.utils.yaml_utils import dump_yaml

    loader = ContractLoader(runtime_context=args.runtime_context)
    base_contract = loader.load(args.base)
    candidate_contract = loader.load(args.candidate)

    decision = GovernanceService().evaluate(
        base_contract,
        candidate_contract,
        effective_date=args.effective_date,
    )
    enforce_governance_gate(decision, GovernanceOperation.PROPOSE)

    result = apply_release_candidate(
        base_contract,
        candidate_contract,
        args.release_tag,
        required_bump=decision.required_version_bump,
    )
    output_path = dump_yaml(contract_to_dict(result.contract), args.output)
    return {
        "contractId": str(result.contract.id or ""),
        "currentVersion": result.current_version,
        "targetVersion": result.target_version,
        "requiredBump": result.required_bump,
        "actualBump": result.actual_bump,
        "releaseTag": result.release_tag,
        "reasons": [r.message for r in decision.reasons],
        "breakingChanges": [asdict(change) for change in decision.policy.breaking_changes],
        "output": str(output_path),
        "governanceDecision": decision.model_dump(mode="json"),
    }


def run_release_classify_repo(args: argparse.Namespace) -> dict[str, Any]:
    from semapact.devops.release_workflow import (
        classify_contracts_in_repo,
        repository_change_to_dict,
    )

    change_context = GovernanceService.create_context(args.effective_date)
    results = classify_contracts_in_repo(
        base_root=args.base_root,
        candidate_root=args.candidate_root,
        context=change_context,
    )
    return {"contracts": [repository_change_to_dict(item) for item in results]}


def run_release_build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    from semapact.devops.release_workflow import (
        batch_manifest_build_to_dict,
        batch_task_to_dict,
        build_batch_release_manifest,
    )

    change_context = GovernanceService.create_context(args.effective_date)
    build = build_batch_release_manifest(
        base_root=args.base_root,
        candidate_root=args.candidate_root,
        context=change_context,
        target_branch=args.target_branch,
        source_branch_prefix=args.source_branch_prefix,
    )
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            [batch_task_to_dict(item) for item in build.tasks], indent=2, sort_keys=True
        ),
        encoding="utf-8",
    )
    payload = batch_manifest_build_to_dict(build)
    payload["output"] = str(output_path)
    return payload


def run_release_create_pr(args: argparse.Namespace) -> dict[str, Any]:
    """Compatibility Git publication workflow retained until a publisher is selected."""
    from semapact.core.loader import ContractLoader
    from semapact.devops.release_workflow import create_release_pull_request

    loader = ContractLoader(runtime_context=args.runtime_context)
    base_contract = loader.load(args.base)
    candidate_contract = loader.load(args.candidate)
    change_context = GovernanceService.create_context(args.effective_date)

    config = _build_git_config(args)
    payload = create_release_pull_request(
        config=config,
        repo_path=_get_repo_path(args),
        contract_repo_path=args.contract_path,
        base_contract=base_contract,
        candidate_contract=candidate_contract,
        release_tag=args.release_tag,
        source_branch=args.source_branch,
        target_branch=args.target_branch,
        context=change_context,
        title=args.title,
        description=args.description,
        commit_message=args.commit_message,
        push=args.push,
    )
    return payload


def run_release_create_prs(args: argparse.Namespace) -> dict[str, Any]:
    from semapact.devops.release_workflow import (
        batch_task_to_dict,
        create_release_pull_requests_from_manifest,
        load_batch_release_tasks,
    )

    config = _build_git_config(args)
    tasks = load_batch_release_tasks(args.manifest)
    payload = create_release_pull_requests_from_manifest(
        config=config,
        repo_path=_get_repo_path(args),
        tasks=tasks,
        push=args.push,
    )
    return {
        "tasks": [batch_task_to_dict(item) for item in tasks],
        "results": payload,
    }
