"""CLI adapter for production-readiness diagnostics."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json

from semapact.application.models.readiness import ReadinessReport
from semapact.application.services.readiness import ReadinessService
from semapact.core.loader import load_contract
from semapact.interfaces.outcomes import ProcessOutcome
from semapact.platforms.git.readiness import GitWorkingTreeReadinessProbe


@dataclass(frozen=True)
class DoctorCommandResult:
    """Rendered readiness output plus its process outcome."""

    output: str
    outcome: ProcessOutcome


def run_doctor(args: argparse.Namespace) -> DoctorCommandResult:
    """Check the deployed prerequisites for the contract-selected runtime."""
    from semapact.platforms.runtime_registry import (
        create_runtime_readiness_probe,
        resolve_runtime_location,
    )

    contract = load_contract(args.contract)
    location = resolve_runtime_location(
        contract,
        server_name=args.server,
        fallback_platform=args.platform,
        fallback_runtime_target=args.runtime,
    )

    execution_config = None
    if location.platform == "databricks":
        from semapact.platforms.databricks.deployment import (
            DatabricksDeploymentExecutionConfig,
        )

        execution_config = DatabricksDeploymentExecutionConfig(
            warehouse_id=args.warehouse_id,
        )

    runtime_probe = create_runtime_readiness_probe(
        location.platform,
        runtime_target=location.runtime_target,
        contract_server=location.contract_server,
        execution_config=execution_config,
    )
    report = ReadinessService(
        (
            runtime_probe,
            GitWorkingTreeReadinessProbe(args.repository_root),
        )
    ).check(
        platform=location.platform,
        runtime_target=location.runtime_target,
    )

    rendered = _json_output(report) if args.output == "json" else _text_output(report)
    return DoctorCommandResult(
        output=rendered,
        outcome=(
            ProcessOutcome.SUCCESS
            if report.ready
            else ProcessOutcome.VALIDATION_FAILED
        ),
    )


def _json_output(report: ReadinessReport) -> str:
    payload = report.model_dump(mode="json")
    payload["ready"] = report.ready
    return json.dumps(
        payload,
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )


def _text_output(report: ReadinessReport) -> str:
    lines = [
        f"Readiness: {'READY' if report.ready else 'NOT_READY'}",
        f"Platform: {report.platform}",
        f"Runtime target: {report.runtime_target}",
        "Checks:",
    ]
    for check in report.checks:
        requirement = "required" if check.required else "optional"
        lines.append(
            f"  [{check.status.value}] {check.check_id} ({requirement}) - {check.summary}"
        )
        if check.remediation:
            lines.append(f"      remediation: {check.remediation}")
    return "\n".join(lines)
