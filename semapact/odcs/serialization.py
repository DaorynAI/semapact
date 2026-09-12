"""Deterministic serialization for the canonical ODCS contract model."""

from __future__ import annotations

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.utils.deterministic import canonical_compact_json


def canonical_contract_json(contract: OpenDataContractStandard) -> str:
    """Return the stable compact JSON representation of one ODCS contract.

    This function defines deterministic serialization only. The canonical logical
    contract model remains ``OpenDataContractStandard``.
    """
    if not isinstance(contract, OpenDataContractStandard):
        raise TypeError(
            "contract must be OpenDataContractStandard, "
            f"got {type(contract).__name__}"
        )
    payload = contract.model_dump(mode="json", by_alias=True, exclude_none=True)
    return canonical_compact_json(payload)
