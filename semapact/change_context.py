"""Explicit business-effective context for lifecycle mutations."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict


class ChangeContext(BaseModel):
    """Business-effective inputs used when a mutation materializes dated state.

    The context is deliberately explicit and has no wall-clock default. It belongs at
    lifecycle/merge mutation boundaries where SemaPact may write facts such as
    `deprecationDate`. Pure governance, release planning, and deployment assessment
    must not depend on it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    effective_date: date
