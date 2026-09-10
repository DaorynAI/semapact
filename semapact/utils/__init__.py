"""Utility exports kept lazy so focused helpers do not import unrelated core modules."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, tuple[str, str]] = {
    "contract_to_dict": ("semapact.utils.schema_utils", "contract_to_dict"),
    "contract_to_model": ("semapact.utils.schema_utils", "contract_to_model"),
    "ensure_schema_key": ("semapact.utils.schema_utils", "ensure_schema_key"),
    "dump_yaml": ("semapact.utils.yaml_utils", "dump_yaml"),
    "load_yaml": ("semapact.utils.yaml_utils", "load_yaml"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
