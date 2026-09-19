"""Application read model for production-readiness diagnostics."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, computed_field, field_validator


class ReadinessStatus(str, Enum):
    """Stable status vocabulary for one readiness check."""

    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    SKIP = "SKIP"


class ReadinessCheck(BaseModel):
    """One secret-safe prerequisite check."""

    model_config = ConfigDict(frozen=True)

    check_id: str
    status: ReadinessStatus
    required: bool
    summary: str
    remediation: str | None = None
    error_type: str | None = None

    @field_validator("check_id", "summary")
    @classmethod
    def _require_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("readiness check text fields must not be empty")
        return cleaned


class ReadinessReport(BaseModel):
    """Provider-neutral readiness report for one runtime target."""

    model_config = ConfigDict(frozen=True)

    platform: str
    runtime_target: str
    checks: tuple[ReadinessCheck, ...]

    @computed_field
    @property
    def ready(self) -> bool:
        """Required checks must pass; optional warnings do not block readiness."""
        return all(
            (not check.required) or check.status is ReadinessStatus.PASS
            for check in self.checks
        )
