"""Shared Databricks runtime-target parsing."""

from __future__ import annotations

from semapact.exceptions import ValidationError


def parse_databricks_runtime_target(value: str) -> tuple[str, str]:
    """Parse the provider-local ``catalog.schema`` target descriptor."""
    parts = tuple(part.strip() for part in value.split("."))
    if len(parts) != 2 or not all(parts):
        raise ValidationError(
            "Databricks runtime target must use catalog.schema format for a data product"
        )
    return parts[0], parts[1]
