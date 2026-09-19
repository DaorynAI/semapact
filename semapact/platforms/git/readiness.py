"""Read-only readiness checks for Git working-tree governance storage."""

from __future__ import annotations

import os
from pathlib import Path

from semapact.application.models.readiness import ReadinessCheck, ReadinessStatus


class GitWorkingTreeReadinessProbe:
    """Validate governance-history storage prerequisites without writing files."""

    key = "history"

    def __init__(
        self,
        repository_root: str | Path,
        *,
        state_directory: str | Path = ".semapact/history",
    ) -> None:
        self._repository_root = Path(repository_root)
        self._state_directory = Path(state_directory)

    def run(self) -> tuple[ReadinessCheck, ...]:
        root = self._repository_root.resolve(strict=False)
        root_check = self._check_repository_root(root)
        if root_check.status is not ReadinessStatus.PASS:
            return (
                root_check,
                ReadinessCheck(
                    check_id="history.storage",
                    status=ReadinessStatus.SKIP,
                    required=True,
                    summary="Governance history storage was not checked because the repository root is invalid.",
                ),
                ReadinessCheck(
                    check_id="git.worktree",
                    status=ReadinessStatus.WARN,
                    required=False,
                    summary="Git worktree integration could not be checked.",
                ),
            )

        return (
            root_check,
            self._check_history_storage(root),
            self._check_git_worktree(root),
        )

    def _check_repository_root(self, root: Path) -> ReadinessCheck:
        if not root.exists() or not root.is_dir():
            return ReadinessCheck(
                check_id="history.repository_root",
                status=ReadinessStatus.FAIL,
                required=True,
                summary="Repository root does not exist or is not a directory.",
                remediation="Point --repository-root at the Git working tree used for SemaPact governance history.",
            )
        return ReadinessCheck(
            check_id="history.repository_root",
            status=ReadinessStatus.PASS,
            required=True,
            summary="Repository root is available.",
        )

    def _check_history_storage(self, root: Path) -> ReadinessCheck:
        state = self._state_directory
        if state.is_absolute() or ".." in state.parts:
            return ReadinessCheck(
                check_id="history.storage",
                status=ReadinessStatus.FAIL,
                required=True,
                summary="Governance history state directory is not repository-relative.",
                remediation="Use a repository-relative history directory inside the governance working tree.",
            )

        target = (root / state).resolve(strict=False)
        if not target.is_relative_to(root):
            return ReadinessCheck(
                check_id="history.storage",
                status=ReadinessStatus.FAIL,
                required=True,
                summary="Governance history storage resolves outside the repository root.",
                remediation="Keep governance history inside the configured repository root.",
            )

        if target.exists() and not target.is_dir():
            return ReadinessCheck(
                check_id="history.storage",
                status=ReadinessStatus.FAIL,
                required=True,
                summary="Governance history path exists but is not a directory.",
                remediation="Replace the conflicting path with a writable history directory.",
            )

        probe_path = target if target.exists() else _nearest_existing_parent(target, root)
        if not os.access(probe_path, os.R_OK | os.W_OK | os.X_OK):
            return ReadinessCheck(
                check_id="history.storage",
                status=ReadinessStatus.FAIL,
                required=True,
                summary="Governance history storage is not readable and writable by the current process.",
                remediation="Grant the SemaPact process read/write access to the governance working tree.",
            )

        return ReadinessCheck(
            check_id="history.storage",
            status=ReadinessStatus.PASS,
            required=True,
            summary="Governance history storage is accessible.",
        )

    def _check_git_worktree(self, root: Path) -> ReadinessCheck:
        if (root / ".git").exists():
            return ReadinessCheck(
                check_id="git.worktree",
                status=ReadinessStatus.PASS,
                required=False,
                summary="Git worktree metadata is present.",
            )
        return ReadinessCheck(
            check_id="git.worktree",
            status=ReadinessStatus.WARN,
            required=False,
            summary="Git worktree metadata was not found.",
            remediation="Use a Git working tree when governance history should be versioned through GitOps.",
        )


def _nearest_existing_parent(target: Path, root: Path) -> Path:
    current = target
    while not current.exists() and current != root:
        current = current.parent
    return current
