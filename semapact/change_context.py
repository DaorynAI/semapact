"""Explicit contextual inputs for deterministic contract change analysis."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict


class ChangeContext(BaseModel):
    """Governance-relevant context supplied explicitly by the caller.

    ``effective_date`` is required and intentionally has no wall-clock default.
    Callers must create the context at an upstream workflow boundary and pass the
    same instance through merge and governance evaluation. Lower layers must not
    regenerate or overwrite this date.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    effective_date: date
