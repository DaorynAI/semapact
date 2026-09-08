from __future__ import annotations

from types import SimpleNamespace

import pytest

from semapact.exceptions import ValidationError
from semapact.platforms.databricks.runtime import DatabricksRuntimeProvider
from semapact.platforms.runtime_registry import create_runtime_provider_registry


def test_unsupported_runtime_provider_is_user_validation() -> None:
    with pytest.raises(ValidationError, match="Unsupported runtime provider 'snowflake'"):
        create_runtime_provider_registry("snowflake")


def test_databricks_runtime_target_syntax_is_user_validation() -> None:
    provider = DatabricksRuntimeProvider(
        client=SimpleNamespace(),
        source_identifier="https://adb.example",
    )

    with pytest.raises(
        ValidationError,
        match="Databricks runtime target must use catalog.schema format",
    ):
        provider.resolve_bindings(runtime_target="main.sales.orders", assets=())
