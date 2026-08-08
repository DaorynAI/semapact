from __future__ import annotations

from pathlib import Path
from typing import Any

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.core.loader import load_contract


def contract_to_model(
    contract_input: OpenDataContractStandard | dict[str, Any] | str | Path,
) -> OpenDataContractStandard:
    """Normalize contract input to OpenDataContractStandard model."""
    if isinstance(contract_input, OpenDataContractStandard):
        return OpenDataContractStandard.model_validate(
            contract_input.model_dump(by_alias=True, exclude_none=True)
        )

    if isinstance(contract_input, dict):
        return OpenDataContractStandard.model_validate(contract_input)

    if isinstance(contract_input, Path):
        return load_contract(str(contract_input))

    if isinstance(contract_input, str):
        return load_contract(contract_input)

    raise TypeError(f"Unsupported contract input type: {type(contract_input)!r}")


def contract_to_dict(
    contract_input: OpenDataContractStandard | dict[str, Any] | str | Path,
) -> dict[str, Any]:
    """Normalize contract input to ODCS dictionary."""
    model = contract_to_model(contract_input)
    return model.model_dump(by_alias=True, exclude_none=True)


def ensure_schema_key(contract_dict: dict[str, Any]) -> str:
    """Return schema key in ODCS dictionary (`schema` or `schema_`)."""
    if isinstance(contract_dict.get("schema"), list):
        return "schema"
    if isinstance(contract_dict.get("schema_"), list):
        return "schema_"
    contract_dict["schema"] = []
    return "schema"
