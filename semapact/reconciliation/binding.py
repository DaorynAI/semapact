"""Compatibility exports for governed runtime asset projection.

The canonical provider-neutral projection lives in :mod:`semapact.runtime`. This
module remains as a compatibility import path for existing reconciliation callers.
"""

from semapact.runtime import RuntimeAssetSpec, runtime_asset_specs_from_contract

__all__ = ["RuntimeAssetSpec", "runtime_asset_specs_from_contract"]
