"""Shared executable identifier validation helpers."""

from __future__ import annotations

import re

from semapact.exceptions import ValidationError


_SIMPLE_SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def validate_simple_sql_identifier(value: str, role: str) -> None:
    """Validate the conservative SQL identifier subset used by safe renderers."""
    if not _SIMPLE_SQL_IDENTIFIER_RE.fullmatch(value):
        raise ValidationError(
            f"Unsupported {role} identifier for executable SQL: '{value}'"
        )
