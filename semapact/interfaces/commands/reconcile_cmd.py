"""CLI adapter for read-only runtime product reconciliation."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from typing import Literal

from semapact.interfaces.outcomes import ProcessOutcome, outcome_from_reconciliation_status
from semapact.platforms.runtime_registry import create_runtime_provider_registry
from semapact.services.reconciliation_service import ReconciliationService, RuntimeReconciliation


@dataclass(frozen=True)
class ReconcileCommandResult:
    """Rendered command output plus its semantic process outcome."""

    output: str
    outcome: ProcessOutcome


def run_reconcile(args: argparse.Namespace) -> ReconcileCommandResult:
    """Execute the provider-neutral reconciliation workflow."""
    registry = create_runtime_provider_registry(args.platform)
    analysis = ReconciliationService(registry).reconcile(
        contract_path=args.contract,
        platform=args.platform,
        runtime_target=args.runtime,
    )
    output_format: Literal["text", "json"] = args.output
    rendered = (
        _format_json(analysis)
        if output_format == "json"
        else _format_text(analysis)
    )
    return ReconcileCommandResult(
        output=rendered,
        outcome=outcome_from_reconciliation_status(analysis.status),
    )


def _format_json(analysis: RuntimeReconciliation) -> str:
    payload = {
        "platform": analysis.platform,
        "runtimeTarget": analysis.runtime_target,
        "status": analysis.status.value,
        "bindings": [
            {
                "governedAsset": binding.governed_asset,
                "observedAsset": binding.observed_asset.model_dump(mode="json"),
            }
            for binding in analysis.bindings
        ],
        "reconciliation": analysis.result.model_dump(mode="json"),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)


def _format_text(analysis: RuntimeReconciliation) -> str:
    result = analysis.result
    lines = [
        f"Status: {analysis.status.value}",
        f"Contract: {result.contract_id}@{result.contract_version}",
        f"Platform: {analysis.platform}",
        f"Runtime: {analysis.runtime_target}",
        f"Observation fingerprint: {result.observation_fingerprint}",
        "Bindings:",
    ]
    for binding in analysis.bindings:
        identity = binding.observed_asset
        physical_name = ".".join((*identity.namespace, identity.asset))
        lines.append(
            f"  - {binding.governed_asset} -> {identity.platform}:{physical_name}"
        )

    if result.differences:
        lines.append("Differences:")
        for difference in result.differences:
            detail = f"  - {difference.reason_code.value} {difference.path}"
            if difference.expected is not None or difference.observed is not None:
                detail += (
                    f" expected={difference.expected!r}"
                    f" observed={difference.observed!r}"
                )
            lines.append(detail)
    else:
        lines.append("Differences: none")

    if result.unverified_paths:
        lines.append("Unverified paths:")
        lines.extend(f"  - {path}" for path in result.unverified_paths)
    else:
        lines.append("Unverified paths: none")

    return "\n".join(lines)
