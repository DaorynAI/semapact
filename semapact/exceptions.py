"""Custom exception hierarchy for SemaPact.

This module defines specific exceptions to support strict error handling
in automated GitOps pipelines and programmatic API usage.
"""


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
