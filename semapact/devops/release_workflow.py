from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from semapact.core.release import (
    PromotionResult,
    classify_contract_change,
    prepare_release_candidate,
)
from semapact.core.release import suggest_release_version
from semapact.devops.pr_creator import (
    PullRequestCreator,
    GitProviderConfig,
)
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
    required_bump: str | None = None
    suggested_release_version: str | None = None
    reasons: list[str] | None = None


@dataclass(slots=True)
class BatchReleaseTask:
    """Explicit per-contract release task for batch orchestration."""

    base: str
    candidate: str
    contract_path: str
    release_tag: str
    source_branch: str
    target_branch: str
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
    base_contract: Any,
    candidate_contract: Any,
    release_tag: str,
    source_branch: str,
    target_branch: str,
    title: str | None = None,
    description: str | None = None,
    commit_message: str | None = None,
    push: bool = False,
) -> dict[str, Any]:
    """Prepare one promoted contract and open a release PR for it."""
    promotion = prepare_release_candidate(
        base_contract, candidate_contract, release_tag
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
    }


def release_plan_to_dict(plan: ReleasePullRequestPlan) -> dict[str, Any]:
    """Serialize a release PR plan for CLI/JSON output."""
    return asdict(plan)


def classify_contracts_in_repo(
    *,
    base_root: str | Path,
    candidate_root: str | Path,
) -> list[RepositoryContractChange]:
    """Compare two contract roots and classify changes per contract file.

    This is a repo-level orchestration helper only. Versioning remains
    per-contract; this function just batches independent contract assessments.
    """
    base_root_path = Path(base_root).expanduser().resolve()
    candidate_root_path = Path(candidate_root).expanduser().resolve()

    base_index = _relative_contract_index(base_root_path)
    candidate_index = _relative_contract_index(candidate_root_path)

    results: list[RepositoryContractChange] = []
    for relative_path in sorted(set(base_index) | set(candidate_index)):
        base_path = base_index.get(relative_path)
        candidate_path = candidate_index.get(relative_path)

        if base_path is None:
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
                )
            )
            continue

        base_model = contract_to_model(load_yaml(base_path))
        candidate_model = contract_to_model(load_yaml(candidate_path))
        assessment = classify_contract_change(base_model, candidate_model)
        if assessment.has_changes:
            results.append(
                RepositoryContractChange(
                    contract_repo_path=relative_path,
                    status="changed",
                    contract_id=str(base_model.id or ""),
                    current_version=str(base_model.version or ""),
                    candidate_version=str(candidate_model.version or ""),
                    required_bump=assessment.required_bump,
                    suggested_release_version=(
                        suggest_release_version(
                            str(base_model.version or ""),
                            assessment.required_bump,
                        )
                        if assessment.required_bump != "none"
                        else None
                    ),
                    reasons=assessment.reasons,
                )
            )
        else:
            results.append(
                RepositoryContractChange(
                    contract_repo_path=relative_path,
                    status="unchanged",
                    contract_id=str(base_model.id or ""),
                    current_version=str(base_model.version or ""),
                    candidate_version=str(candidate_model.version or ""),
                    required_bump="none",
                    suggested_release_version=None,
                    reasons=assessment.reasons,
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
        results.append(
            create_release_pull_request(
                config=config,
                repo_path=repo_path,
                contract_repo_path=task.contract_path,
                base_contract=load_yaml(task.base),
                candidate_contract=load_yaml(task.candidate),
                release_tag=task.release_tag,
                source_branch=task.source_branch,
                target_branch=task.target_branch,
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
    target_branch: str = "release",
    source_branch_prefix: str = "release/",
) -> BatchReleaseManifestBuild:
    """Build an editable batch manifest from repo-level contract changes.

    Only changed contracts produce manifest tasks. Added and removed contracts
    are skipped because initial releases/removals need explicit handling.
    """
    changes = classify_contracts_in_repo(
        base_root=base_root,
        candidate_root=candidate_root,
    )
    base_root_path = Path(base_root).expanduser().resolve()
    candidate_root_path = Path(candidate_root).expanduser().resolve()

    tasks: list[BatchReleaseTask] = []
    skipped: list[RepositoryContractChange] = []
    for change in changes:
        if change.status != "changed" or change.required_bump == "none":
            skipped.append(change)
            continue

        contract_key = _contract_release_key(change)
        next_version = change.suggested_release_version or suggest_release_version(
            str(change.current_version or "0.0.0"),
            str(change.required_bump or "none"),
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
    return asdict(change)


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
