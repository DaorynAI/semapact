"""Interface-independent application use cases for SemaPact."""

from semapact.application.errors import (
    ApplicationDependencyUnavailableError,
    ApplicationServiceError,
)
from semapact.application.service import SemaPactApplicationService

__all__ = [
    "ApplicationDependencyUnavailableError",
    "ApplicationServiceError",
    "SemaPactApplicationService",
]
