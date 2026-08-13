from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from semapact.core.release import (
    PromotionResult,
    RequiredBump,
    apply_release_candidate,
    suggest_release_version,
)
from semapact.devops.pr_creator import (
    GitProviderConfig,
    PullRequestCreator,
)
from semapact.exceptions import GovernanceBlockedError
from semapact.governance import (
    ChangeContext,
    DecisionResult,
    GovernanceDecision,
    GovernanceOperation,
    enforce_governance_gate,
    evaluate_governance_decision,
)
from open_data_contract_standard.model import OpenDataContractStandard
from semapact.utils.schema_utils import contract_to_model
from semapact.utils.yaml_utils import dump_yaml, list_yaml_documents, load_yaml


@dataclass(slots=True)
class ReleasePullRequestPlan:
    """Prepared per-contract release PR payload."""

    contract_id: str
    current_version: str
    target_version: str
    required_bump: str
    actual_bump: str
    release_tag: str
    contract_repo_path: str
    source_branch: str
    target_branch: str
    commit_message: str
    title: str
    description: str


@dataclass(slots=True)
class RepositoryContractChange:
    """Per-contract change status within a multi-contract repo comparison."""

    contract_repo_path: str
    status: str
    contract_id: str | None = None
    current_version: str | None = None
    candidate_version: str | None = None
    required_bump: RequiredBump | None = "none"
    suggested_release_version: str | None = None
    reasons: list[str] | None = None
    governance_decision: GovernanceDecision | None = None


@dataclass(slots=True)
class BatchReleaseTask:
    """Explicit per-contract release task for batch orchestration."""

    base: str
    candidate: str
    contract_path: str
    release_tag: str
    source_branch: str
    target_branch: str
    effective_date: str
    title: str | None = None
    description: str | None = None
    commit_message: str | None = None


@dataclass(slots=True)
class BatchReleaseManifestBuild:
    """Generated batch manifest plus skipped contract summary."""

    tasks: list[BatchReleaseTask]
    skipped: list[RepositoryContractChange]


def build_release_pr_plan(
    *,
    promotion: PromotionResult,
    contract_repo_path: str,
    source_branch: str,
    target_branch: str,
    title: str | None = None,
    description: str | None = None,
    commit_message: str | None = None,
) -> ReleasePullRequestPlan:
    """Build a per-contract release PR plan from a prepared promotion result."""
    contract_id = str(promotion.contract.id or "")
    target_version = promotion.target_version
    default_title = f"Release {contract_id} {target_version}"
    default_commit = f"release({contract_id}): prepare {target_version}"
    default_description = (
        f"Prepare release for contract `{contract_id}`.\n\n"
        f"- current version: `{promotion.current_version}`\n"
        f"- target version: `{promotion.target_version}`\n"
        f"- required bump: `{promotion.required_bump}`\n"
        f"- actual bump: `{promotion.actual_bump}`\n"
        f"- release tag: `{promotion.release_tag}`\n"
    )
    return ReleasePullRequestPlan(
        contract_id=contract_id,
        current_version=promotion.current_version,
        target_version=target_version,
        required_bump=promotion.required_bump,
        actual_bump=promotion.actual_bump,
        release_tag=promotion.release_tag,
        contract_repo_path=contract_repo_path,
        source_branch=source_branch,
        target_branch=target_branch,
        commit_message=commit_message or default_commit,
        title=title or default_title,
        description=description or default_description,
    )


def create_release_pull_request(
    *,
    config: GitProviderConfig,
    repo_path: str,
    contract_repo_path: str,
    base_contract: OpenDataContractStandard,
    candidate_contract: OpenDataContractStandard,
    release_tag: str,
    source_branch: str,
    target_branch: str,
    context: ChangeContext,
    title: str | None = None,
    description: str | None = None,
    commit_message: str | None = None,
    push: bool = False,
) -> dict[str, Any]:
    """Prepare one promoted contract and open a release PR for it."""
    # 1. Authoritative decision evaluation and PROPOSE gate enforcement before file write or Git/PR actions
    decision = evaluate_governance_decision(
        base_contract,
        candidate_contract,
        context=context,
    )
    enforce_governance_gate(decision, GovernanceOperation.PROPOSE)

    promotion = apply_release_candidate(
        base_contract,
        candidate_contract,
        release_tag,
        required_bump=decision.required_version_bump,
    )
    repo_root = Path(repo_path).expanduser().resolve()
    contract_path = repo_root / contract_repo_path
    dump_yaml(promotion.contract, contract_path)

    plan = build_release_pr_plan(
        promotion=promotion,
        contract_repo_path=contract_repo_path,
        source_branch=source_branch,
        target_branch=target_branch,
        title=title,
        description=description,
        commit_message=commit_message,
    )

    creator = PullRequestCreator(config=config)
    pr_payload = creator.create_update_pr(
        repo_path=str(repo_root),
        source_branch=source_branch,
        target_branch=target_branch,
        commit_message=plan.commit_message,
        title=plan.title,
        description=plan.description,
        paths=[contract_repo_path],
        push=push,
    )
    return {
        "promotion": {
            "contractId": plan.contract_id,
            "currentVersion": plan.current_version,
            "targetVersion": plan.target_version,
            "requiredBump": plan.required_bump,
            "actualBump": plan.actual_bump,
            "releaseTag": plan.release_tag,
            "contractPath": plan.contract_repo_path,
            "sourceBranch": plan.source_branch,
            "targetBranch": plan.target_branch,
        },
        "pullRequest": pr_payload,
        "governanceDecision": decision.model_dump(mode="json"),
    }


def release_plan_to_dict(plan: ReleasePullRequestPlan) -> dict[str, Any]:
    """Serialize a release PR plan for CLI/JSON output."""
    return asdict(plan)


def classify_contracts_in_repo(
    *,
    base_root: str | Path,
    candidate_root: str | Path,
    context: ChangeContext,
) -> list[RepositoryContractChange]:
    """Compare two contract roots and classify changes per contract file based on GovernanceDecision."""
    base_root_path = Path(base_root).expanduser().resolve()
    candidate_root_path = Path(candidate_root).expanduser().resolve()

    base_index = _relative_contract_index(base_root_path)
    candidate_index = _relative_contract_index(candidate_root_path)

    results: list[RepositoryContractChange] = []
    for relative_path in sorted(set(base_index) | set(candidate_index)):
        base_path = base_index.get(relative_path)
        candidate_path = candidate_index.get(relative_path)

        if base_path is None:
            assert candidate_path is not None
            candidate_model = contract_to_model(load_yaml(candidate_path))
            results.append(
                RepositoryContractChange(
                    contract_repo_path=relative_path,
                    status="added",
                    contract_id=str(candidate_model.id or ""),
                    current_version=None,
                    candidate_version=str(candidate_model.version or ""),
                    required_bump=None,
                    suggested_release_version=None,
                    reasons=[
                        "New governed contract; initial release handled separately"
                    ],
                    governance_decision=None,
                )
            )
            continue

        if candidate_path is None:
            base_model = contract_to_model(load_yaml(base_path))
            results.append(
                RepositoryContractChange(
                    contract_repo_path=relative_path,
                    status="removed",
                    contract_id=str(base_model.id or ""),
                    current_version=str(base_model.version or ""),
                    candidate_version=None,
                    required_bump=None,
                    suggested_release_version=None,
                    reasons=[
                        "Governed contract missing from candidate root; manual review required"
                    ],
                    governance_decision=None,
                )
            )
            continue

        base_model = contract_to_model(load_yaml(base_path))
        candidate_model = contract_to_model(load_yaml(candidate_path))

        decision = evaluate_governance_decision(
            base_model,
            candidate_model,
            context=context,
        )
        reasons_list = [r.message for r in decision.reasons] or ["No contract changes detected"]

        status = (
            "blocked"
            if decision.decision == DecisionResult.BLOCK
            else ("changed" if decision.evidence.has_changes else "unchanged")
        )

        results.append(
            RepositoryContractChange(
                contract_repo_path=relative_path,
                status=status,
                contract_id=str(base_model.id or ""),
                current_version=str(base_model.version or ""),
                candidate_version=str(candidate_model.version or ""),
                required_bump=decision.required_version_bump,
                suggested_release_version=(
                    suggest_release_version(
                        str(base_model.version or ""),
                        decision.required_version_bump,
                    )
                    if decision.required_version_bump != "none"
                    else None
                ),
                reasons=reasons_list,
                governance_decision=decision,
            )
        )

    return results


def create_release_pull_requests_from_manifest(
    *,
    config: GitProviderConfig,
    repo_path: str,
    tasks: list[BatchReleaseTask],
    push: bool = False,
) -> list[dict[str, Any]]:
    """Run explicit per-contract release PR automation from a batch manifest."""
    results: list[dict[str, Any]] = []
    for task in tasks:
        base_contract = contract_to_model(load_yaml(task.base))
        candidate_contract = contract_to_model(load_yaml(task.candidate))
        task_context = ChangeContext(effective_date=task.effective_date)

        results.append(
            create_release_pull_request(
                config=config,
                repo_path=repo_path,
                contract_repo_path=task.contract_path,
                base_contract=base_contract,
                candidate_contract=candidate_contract,
                release_tag=task.release_tag,
                source_branch=task.source_branch,
                target_branch=task.target_branch,
                context=task_context,
                title=task.title,
                description=task.description,
                commit_message=task.commit_message,
                push=push,
            )
        )
    return results


def build_batch_release_manifest(
    *,
    base_root: str | Path,
    candidate_root: str | Path,
    context: ChangeContext,
    target_branch: str = "release",
    source_branch_prefix: str = "release/",
) -> BatchReleaseManifestBuild:
    """Build an editable batch manifest from repo-level contract changes."""
    changes = classify_contracts_in_repo(
        base_root=base_root,
        candidate_root=candidate_root,
        context=context,
    )
    base_root_path = Path(base_root).expanduser().resolve()
    candidate_root_path = Path(candidate_root).expanduser().resolve()

    tasks: list[BatchReleaseTask] = []
    skipped: list[RepositoryContractChange] = []
    for change in changes:
        if change.status != "changed" or change.required_bump == "none":
            skipped.append(change)
            continue

        # Enforce PROPOSE gate using GovernanceBlockedError exception catching to handle blocked changes
        if change.governance_decision is not None:
            try:
                enforce_governance_gate(
                    change.governance_decision,
                    GovernanceOperation.PROPOSE,
                )
            except GovernanceBlockedError:
                skipped.append(change)
                continue

        contract_key = _contract_release_key(change)
        next_version = change.suggested_release_version or suggest_release_version(
            str(change.current_version or "0.0.0"),
            change.required_bump or "none",
        )
        release_tag = f"{contract_key}/v{next_version}"
        source_branch = (
            f"{source_branch_prefix}{_branch_safe_name(contract_key)}-v{next_version}"
        )

        tasks.append(
            BatchReleaseTask(
                base=str(base_root_path / change.contract_repo_path),
                candidate=str(candidate_root_path / change.contract_repo_path),
                contract_path=change.contract_repo_path,
                release_tag=release_tag,
                source_branch=source_branch,
                target_branch=target_branch,
                effective_date=context.effective_date.isoformat(),
            )
        )

    return BatchReleaseManifestBuild(tasks=tasks, skipped=skipped)


def load_batch_release_tasks(path: str | Path) -> list[BatchReleaseTask]:
    """Load a JSON batch manifest for per-contract release orchestration."""
    manifest_path = Path(path).expanduser().resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Batch release manifest must be a JSON array")
    return [BatchReleaseTask(**item) for item in payload]


def repository_change_to_dict(change: RepositoryContractChange) -> dict[str, Any]:
    """Serialize repo-level change result for CLI/JSON output."""
    gov_dec_dict = (
        change.governance_decision.model_dump(mode="json")
        if change.governance_decision is not None
        else None
    )

    return {
        "contract_repo_path": change.contract_repo_path,
        "contractRepoPath": change.contract_repo_path,
        "status": change.status,
        "contract_id": change.contract_id,
        "contractId": change.contract_id,
        "current_version": change.current_version,
        "currentVersion": change.current_version,
        "candidate_version": change.candidate_version,
        "candidateVersion": change.candidate_version,
        "required_bump": change.required_bump,
        "requiredBump": change.required_bump,
        "suggested_release_version": change.suggested_release_version,
        "suggestedReleaseVersion": change.suggested_release_version,
        "reasons": change.reasons,
        "governance_decision": gov_dec_dict,
        "governanceDecision": gov_dec_dict,
    }


def batch_task_to_dict(task: BatchReleaseTask) -> dict[str, Any]:
    """Serialize a batch release task for debugging/output."""
    return asdict(task)


def batch_manifest_build_to_dict(build: BatchReleaseManifestBuild) -> dict[str, Any]:
    """Serialize manifest build result for CLI/JSON output."""
    return {
        "tasks": [batch_task_to_dict(task) for task in build.tasks],
        "skipped": [repository_change_to_dict(change) for change in build.skipped],
    }


def _relative_contract_index(root: Path) -> dict[str, Path]:
    if not root.exists():
        return {}
    documents = [Path(path) for path in list_yaml_documents(root)]
    return {str(path.relative_to(root)): path for path in documents}


def _contract_release_key(change: RepositoryContractChange) -> str:
    contract_id = str(change.contract_id or "").strip()
    if contract_id:
        return contract_id
    return Path(change.contract_repo_path).stem


def _branch_safe_name(value: str) -> str:
    cleaned = "".join(
        char if char.isalnum() or char in {"-", "_"} else "-" for char in value.strip()
    )
    return cleaned.strip("-") or "contract"
