"""Custom exception hierarchy for SemaPact.

This module defines specific exceptions to support strict error handling
in automated GitOps pipelines and programmatic API usage.
"""

from __future__ import annotations

from typing import Any


class SemaPactError(Exception):
    """The base exception for SemaPact."""

    pass


class ValidationError(SemaPactError):
    """Raised when a contract fails governance or structure validation."""

    pass


class MergeConflictError(SemaPactError):
    """Raised by the merge engine when business and technical metadata fatally conflict."""

    pass


class LifecycleError(SemaPactError):
    """Raised for invalid promotion or deployment actions."""

    pass


class StorageError(SemaPactError):
    """Wraps Azure ADLS / file system / Unity Catalog connection errors."""

    pass


class GovernanceBlockedError(SemaPactError):
    """Raised when a pipeline run or contract change is blocked by a GovernanceDecision."""

    def __init__(
        self,
        message: str,
        decision: Any = None,
        manifest_path: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.decision = decision
        self.manifest_path = manifest_path

