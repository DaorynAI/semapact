"""Governed data-product asset specs for runtime binding."""

from __future__ import annotations

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.exceptions import ValidationError
from semapact.lifecycle.identity import normalize_identity_name
from semapact.observation.providers import RuntimeAssetSpec


def runtime_asset_specs_from_contract(
    contract: OpenDataContractStandard,
) -> tuple[RuntimeAssetSpec, ...]:
    """Project governed schemas into logical asset specs without changing identity.

    ``schema.name`` remains the governed logical identity. ``physicalName`` is used
    only as a runtime binding hint and falls back to the governed name when absent.
    """
    specs: list[RuntimeAssetSpec] = []
    seen: set[str] = set()

    for schema in contract.schema_ or []:
        raw_name = getattr(schema, "name", None)
        if raw_name is None:
            raise ValidationError("Governed schema name is required for runtime binding")
        governed_asset = normalize_identity_name(str(raw_name), "Schema")
        if governed_asset in seen:
            raise ValidationError(
                f"Duplicate canonical governed asset identity found: '{governed_asset}'"
            )
        seen.add(governed_asset)

        physical_name_value = getattr(schema, "physicalName", None)
        physical_name = str(physical_name_value).strip() if physical_name_value else ""
        specs.append(
            RuntimeAssetSpec(
                governed_asset=governed_asset,
                physical_name=physical_name or str(raw_name).strip(),
            )
        )

    return tuple(sorted(specs, key=lambda item: item.governed_asset))
