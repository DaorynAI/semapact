"""Databricks identifier validation shared by provider write-side components."""

from __future__ import annotations

import re

from semapact.exceptions import ValidationError


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def validate_databricks_identifier(value: str, role: str) -> None:
    """Fail closed on identifiers outside the supported executable subset."""
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValidationError(
            f"Unsupported Databricks {role} identifier for schema evolution: '{value}'"
        )
