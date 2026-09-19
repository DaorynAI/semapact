"""Interface-independent application use cases for SemaPact."""

from semapact.application.errors import (
    ApplicationCapabilityUnavailableError,
    ApplicationServiceError,
)
from semapact.application.service import SemaPactApplicationService

__all__ = [
    "ApplicationCapabilityUnavailableError",
    "ApplicationServiceError",
    "SemaPactApplicationService",
]
