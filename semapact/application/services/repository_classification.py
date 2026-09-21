"""Repository-level contract change classification for central contract repositories."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

from semapact.change_context import ChangeContext
from semapact.governance import DecisionResult, GovernanceDecision, evaluate_governance_decision
from semapact.utils.schema_utils import contract_to_model
from semapact.utils.yaml_utils import list_yaml_documents, load_yaml
from semapact.versioning import RequiredBump, suggest_release_version


@dataclass(slots=True)
class RepositoryContractChange:
    """Per-contract change status within a repository comparison."""

    contract_repo_path: str
    status: str
    contract_id: str | None = None
    current_version: str | None = None
    candidate_version: str | None = None
    required_bump: RequiredBump | None = "none"
    suggested_release_version: str | None = None
    reasons: list[str] | None = None
    governance_decision: GovernanceDecision | None = None


def classify_contracts_in_repo(
    *,
    base_root: str | Path,
    candidate_root: str | Path,
    context: ChangeContext,
) -> list[RepositoryContractChange]:
    """Compare two contract roots using the canonical governance evaluator."""
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
            candidate = contract_to_model(load_yaml(candidate_path))
            results.append(
                RepositoryContractChange(
                    contract_repo_path=relative_path,
                    status="added",
                    contract_id=str(candidate.id or ""),
                    candidate_version=str(candidate.version or ""),
                    required_bump=None,
                    reasons=["New governed contract"],
                )
            )
            continue

        if candidate_path is None:
            base = contract_to_model(load_yaml(base_path))
            results.append(
                RepositoryContractChange(
                    contract_repo_path=relative_path,
                    status="removed",
                    contract_id=str(base.id or ""),
                    current_version=str(base.version or ""),
                    required_bump=None,
                    reasons=["Governed contract missing from candidate root"],
                )
            )
            continue

        base = contract_to_model(load_yaml(base_path))
        candidate = contract_to_model(load_yaml(candidate_path))
        decision = evaluate_governance_decision(base, candidate, context=context)
        status = (
            "blocked"
            if decision.decision is DecisionResult.BLOCK
            else ("changed" if decision.evidence.has_changes else "unchanged")
        )
        required_bump = decision.required_version_bump
        results.append(
            RepositoryContractChange(
                contract_repo_path=relative_path,
                status=status,
                contract_id=str(base.id or ""),
                current_version=str(base.version or ""),
                candidate_version=str(candidate.version or ""),
                required_bump=required_bump,
                suggested_release_version=(
                    suggest_release_version(str(base.version or ""), required_bump)
                    if required_bump != "none"
                    else None
                ),
                reasons=[reason.message for reason in decision.reasons]
                or ["No contract changes detected"],
                governance_decision=decision,
            )
        )
    return results


def repository_change_to_dict(change: RepositoryContractChange) -> dict[str, Any]:
    """Serialize repository classification for CLI and CI matrix consumers."""
    decision = (
        change.governance_decision.model_dump(mode="json")
        if change.governance_decision is not None
        else None
    )
    return {
        "contract_repo_path": change.contract_repo_path,
        "contractRepoPath": change.contract_repo_path,
        "artifact_key": _artifact_key(change.contract_repo_path),
        "artifactKey": _artifact_key(change.contract_repo_path),
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
        "governance_decision": decision,
        "governanceDecision": decision,
    }


def _relative_contract_index(root: Path) -> dict[str, Path]:
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): path
        for path in (Path(item) for item in list_yaml_documents(root))
    }


def _artifact_key(contract_repo_path: str) -> str:
    """Return a collision-resistant filesystem/artifact key for one repo-relative path."""
    return hashlib.sha256(contract_repo_path.encode("utf-8")).hexdigest()
