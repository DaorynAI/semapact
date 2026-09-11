"""Application result models for runtime reconciliation use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from semapact.observation import RuntimeAssetBinding
from semapact.reconciliation import ReconciliationResult, RuntimeDriftStatus


@dataclass(frozen=True)
class RuntimeReconciliation:
    """One complete read-only reconciliation of a governed data product."""

    platform: str
    runtime_target: str
    runtime_source: Literal["contract", "cli"]
    server_name: str | None
    bindings: tuple[RuntimeAssetBinding, ...]
    result: ReconciliationResult
    status: RuntimeDriftStatus
