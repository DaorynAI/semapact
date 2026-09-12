"""Canonical ODCS serialization shared by deterministic contract artifacts."""

from __future__ import annotations

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.utils.deterministic import canonical_compact_json


def canonical_contract_json(contract: OpenDataContractStandard) -> str:
    """Return the stable compact JSON representation of one ODCS contract.

    This function defines serialization only. It does not assign governance meaning,
    semantic-version meaning, or persistence identity.
    """
    if not isinstance(contract, OpenDataContractStandard):
        raise TypeError(
            "contract must be OpenDataContractStandard, "
            f"got {type(contract).__name__}"
        )
    payload = contract.model_dump(mode="json", by_alias=True, exclude_none=True)
    return canonical_compact_json(payload)
