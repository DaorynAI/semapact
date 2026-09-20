from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from semapact.core.config_schema import (
    DeltaOperationalHistoryConfig,
    SQLiteOperationalHistoryConfig,
    SemaPactConfigSchema,
    operational_history_uri_from_config,
    parse_operational_history_config,
)


def test_operational_history_config_is_disabled_when_omitted() -> None:
    assert parse_operational_history_config(None) is None
    assert operational_history_uri_from_config(None) is None


def test_sqlite_operational_history_config_is_typed() -> None:
    config = parse_operational_history_config(
        {
            "backend": "sqlite",
            "path": ".semapact/operational.db",
        }
    )

    assert isinstance(config, SQLiteOperationalHistoryConfig)
    assert config.as_uri() == "sqlite:///.semapact/operational.db"


def test_delta_operational_history_config_is_typed() -> None:
    config = parse_operational_history_config(
        {
            "backend": "delta",
            "table_uri": "s3://governance/semapact/history",
        }
    )

    assert isinstance(config, DeltaOperationalHistoryConfig)
    assert (
        config.as_uri()
        == "delta:///s3://governance/semapact/history"
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"backend": "sqlite"},
        {"backend": "delta"},
        {"backend": "git", "path": ".semapact/history"},
        {"backend": "sqlite", "path": "", "extra": "forbidden"},
    ],
)
def test_invalid_operational_history_config_fails_closed(payload) -> None:
    with pytest.raises(PydanticValidationError):
        parse_operational_history_config(payload)


def test_root_config_schema_exposes_operational_backend_discriminator() -> None:
    schema = SemaPactConfigSchema.model_json_schema()

    assert "history" in schema["properties"]
    rendered = str(schema)
    assert "sqlite" in rendered
    assert "delta" in rendered
    assert "discriminator" in rendered
