"""CLI adapter for read-only M1 runtime reconciliation."""

from __future__ import annotations

import argparse
import json

from semapact.reconciliation import serialize_reconciliation_result
from semapact.services import ReconciliationAnalysis, ReconciliationService


def run_reconcile(args: argparse.Namespace) -> ReconciliationAnalysis:
    """Delegate one CLI reconciliation request to the application service."""
    return ReconciliationService().reconcile_databricks_table(
        contract_path=args.contract,
        table_fqn=args.source,
        workspace_url=args.workspace_url,
        token=args.token,
        profile=args.profile,
        runtime_context=args.runtime_context,
    )


def format_reconciliation_json(analysis: ReconciliationAnalysis) -> str:
    """Return deterministic machine-readable reconciliation output."""
    payload = {
        "runtimeTarget": analysis.runtime_target,
        "status": analysis.status.value,
        "reconciliation": json.loads(serialize_reconciliation_result(analysis.result)),
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def format_reconciliation_text(analysis: ReconciliationAnalysis) -> str:
    """Return deterministic human-readable reconciliation output."""
    result = analysis.result
    lines = [
        f"Contract: {result.contract_id}",
        f"Version: {result.contract_version}",
        f"Runtime: {analysis.runtime_target}",
        f"Status: {analysis.status.value}",
        "",
        "Differences:",
    ]

    if result.differences:
        for difference in result.differences:
            detail = f"- {difference.reason_code.value} {difference.path}"
            if difference.expected is not None or difference.observed is not None:
                detail += (
                    f" expected={difference.expected!r}"
                    f" observed={difference.observed!r}"
                )
            lines.append(detail)
    else:
        lines.append("- none")

    lines.extend(["", "Unverified:"])
    if result.unverified_paths:
        lines.extend(f"- {path}" for path in result.unverified_paths)
    else:
        lines.append("- none")

    return "\n".join(lines)
