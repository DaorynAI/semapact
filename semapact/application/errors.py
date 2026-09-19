"""Stable application-boundary errors shared by all clients."""

from __future__ import annotations


class ApplicationServiceError(RuntimeError):
    """Base error for application-boundary failures owned by SemaPact."""


class ApplicationCapabilityUnavailableError(ApplicationServiceError):
    """A supported application capability is not configured for this service instance."""

    def __init__(self, capability: str) -> None:
        cleaned = _required_text(capability, "capability")
        super().__init__(f"Application capability is not configured: {cleaned}")
        self.capability = cleaned


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be str")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty")
    return cleaned
