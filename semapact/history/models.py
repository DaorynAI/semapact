"""Immutable history-owned relationship models.

These models record cross-artifact audit relationships without redefining the
canonical domain artifacts they connect.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator


class ChangeSetDecisionLink(BaseModel):
    """Audit provenance linking one ChangeSet to one GovernanceDecision outcome."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    change_set_id: str
    decision_id: str

    @field_validator("change_set_id", "decision_id")
    @classmethod
    def _require_non_empty_text(cls, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("history link identifiers must be strings")
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("history link identifiers must not be empty")
        return cleaned
