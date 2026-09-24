"""Typed configuration schema for supported SemaPact configuration sections."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator


def _clean_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class DatabricksConfig(BaseModel):
    """Project/global Databricks connection hints.

    These are composition hints only. Missing values are intentionally left to
    the Databricks SDK unified-authentication chain.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_url: str | None = None
    token: str | None = None
    profile: str | None = None

    @field_validator("workspace_url", "token", "profile")
    @classmethod
    def _normalize_optional_hint(cls, value: str | None) -> str | None:
        return _clean_optional_string(value)


class _OperationalHistoryConfig(BaseModel):
    """Shared immutable configuration contract for operational history backends."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    backend: str


class SQLiteOperationalHistoryConfig(_OperationalHistoryConfig):
    """Local SQLite operational history configuration."""

    backend: Literal["sqlite"]
    path: str = Field(min_length=1)

    @field_validator("path")
    @classmethod
    def _require_path(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("SQLite operational history path must not be empty")
        return cleaned

    def as_uri(self) -> str:
        return f"sqlite:///{self.path}"


class DeltaOperationalHistoryConfig(_OperationalHistoryConfig):
    """Delta Lake operational history configuration."""

    backend: Literal["delta"]
    table_uri: str = Field(min_length=1)

    @field_validator("table_uri")
    @classmethod
    def _require_table_uri(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Delta operational history table_uri must not be empty")
        return cleaned

    def as_uri(self) -> str:
        return f"delta:///{self.table_uri}"


OperationalHistoryConfig = Annotated[
    SQLiteOperationalHistoryConfig | DeltaOperationalHistoryConfig,
    Field(discriminator="backend"),
]


class HistoryConfig(BaseModel):
    """Typed history configuration while unrelated configuration remains extensible."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operational: OperationalHistoryConfig | None = None


class SemaPactConfigSchema(BaseModel):
    """Incremental root schema for project/global SemaPact configuration."""

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://semapact.org/schemas/semapact-config.schema.json",
        },
    )

    databricks: DatabricksConfig | None = None
    history: HistoryConfig | None = None


_OPERATIONAL_HISTORY_ADAPTER = TypeAdapter(OperationalHistoryConfig)


def parse_databricks_config(value: object) -> DatabricksConfig | None:
    """Validate the databricks config subsection fail closed."""
    if value is None:
        return None
    return DatabricksConfig.model_validate(value)


def parse_operational_history_config(
    value: object,
) -> OperationalHistoryConfig | None:
    """Validate the history.operational config subsection fail closed."""
    if value is None:
        return None
    return _OPERATIONAL_HISTORY_ADAPTER.validate_python(value)


def operational_history_uri_from_config(value: object) -> str | None:
    """Return the normalized sink URI represented by typed configuration."""
    config = parse_operational_history_config(value)
    return config.as_uri() if config is not None else None


def published_config_json_schema() -> dict[str, object]:
    """Return the canonical machine-readable SemaPact configuration schema."""
    return SemaPactConfigSchema.model_json_schema()
