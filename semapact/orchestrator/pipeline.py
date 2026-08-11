"""SemaPact orchestration pipeline for import, merge, validation, and export.

This module is not the interactive draft-editing workflow used by the UI.
Instead, it is the automation layer for batch and CI/CD scenarios where we:

1. import or generate a technical contract from a source system
2. load an existing lifecycle-governed contract from storage/Git
3. merge technical updates into the governed contract
4. validate the merged result
5. evaluate lifecycle policy
6. export downstream artifacts such as GE suites and CI manifests

Think of this module as the non-interactive "pipeline runner" for SemaPact.
It is useful for engineering automation, scheduled imports, and GitOps flows.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from open_data_contract_standard.model import OpenDataContractStandard

from datacontract.data_contract import DataContract

from semapact.exceptions import GovernanceBlockedError
from semapact.governance import (
    DecisionResult,
    GovernanceDecision,
    evaluate_governance_decision,
)
from semapact.importers.unity_importer import import_unity_contract
from semapact.core.loader import ContractLoader
from semapact.core.validator import ContractValidator, ValidationReport
from semapact.devops.audit import AuditMetadata
from semapact.lifecycle.merge_engine import ContractMergeEngine, MergeResult
from semapact.lifecycle.policy import PolicyEvaluation, evaluate_merge_policy
from semapact.quality.ge_exporter import GreatExpectationsExporter
from semapact.utils.schema_utils import contract_to_dict
from semapact.utils.yaml_utils import dump_yaml

ImportSourceType = str


def write_decision_manifest(
    decision: GovernanceDecision,
    ci_manifest_path: str | Path,
    audit_metadata: AuditMetadata | None = None,
) -> Path:
    """Write decision-only manifest without requiring external artifact creation."""
    resolved_path = Path(ci_manifest_path).expanduser().resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "governanceDecision": decision.to_dict(),
        "valid": decision.validation.valid,
        "policyValid": decision.policy.valid,
        "idViolation": decision.policy.id_violation,
        "versionViolation": decision.policy.version_violation,
        "issues": [asdict(issue) for issue in decision.validation.issues],
        "breakingChanges": [v.to_dict() for v in decision.policy.violations if v.code == "POLICY_BREAKING_CHANGE"],
        "conflicts": [],
        "artifacts": {},
        "audit": asdict(audit_metadata) if audit_metadata is not None else None,
    }
    resolved_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return resolved_path


@dataclass(slots=True)
class PipelineArtifacts:
    """Artifacts produced by a contract pipeline run."""

    merged_contract_path: Path
    ge_suite_path: Path
    ci_manifest_path: Path


@dataclass(slots=True)
class ContractPipeline:
    """Orchestrate SemaPact import, merge, export, and CI artifact generation.

    Purpose:
    - Provide one non-UI entrypoint for technical schema ingestion and governed
      contract artifact generation.
    - Encapsulate the standard execution order for automation:
      import -> merge -> validate -> policy check -> export artifacts.

    Important boundary:
    - This pipeline works with the canonical lifecycle-governed contract.
    - It is not the user draft workflow. UI draft save/analyze flows belong to
      the service layer and governance adapters.
    """

    runtime_context: str = "auto"
    loader: ContractLoader = field(init=False)
    validator: ContractValidator = field(init=False)
    merge_engine: ContractMergeEngine = field(init=False)
    ge_exporter: GreatExpectationsExporter = field(init=False)

    def __post_init__(self) -> None:
        """Initialize shared collaborators for pipeline execution."""
        self.loader = ContractLoader(runtime_context=self.runtime_context)
        self.validator = ContractValidator()
        self.merge_engine = ContractMergeEngine()
        self.ge_exporter = GreatExpectationsExporter()

    def import_schema(
        self,
        source_type: ImportSourceType,
        source: str,
        *,
        existing_contract: OpenDataContractStandard | None = None,
        uc_workspace_url: str | None = None,
        uc_token: str | None = None,
        import_args: dict[str, Any] | None = None,
    ) -> OpenDataContractStandard:
        """Import a technical contract from a supported source type."""
        import_args = import_args or {}
        normalized = source_type.strip().lower()

        if normalized in {"uc", "unity"}:
            return import_unity_contract(
                table_fqn=source,
                workspace_url=uc_workspace_url,
                token=uc_token,
                **import_args,
            )

        try:
            imported = DataContract.import_from_source(
                format=normalized,
                source=source,
                **import_args,
            )
        except ValueError as exc:
            from semapact.exceptions import ValidationError

            raise ValidationError(f"Unsupported source_type: {source_type}") from exc

        if existing_contract is not None:
            return self.merge_engine.merge(
                imported,
                existing_contract,
            ).contract

        return imported

    def merge_contract_updates(
        self,
        source_contract: OpenDataContractStandard,
        business_contract: OpenDataContractStandard,
        *,
        fail_on_conflict: bool = False,
    ) -> MergeResult:
        """Merge a technical source contract into a business contract."""
        return self.merge_engine.merge(
            source_contract,
            business_contract,
            fail_on_conflict=fail_on_conflict,
        )

    def validate_contract(
        self, contract: OpenDataContractStandard
    ) -> ValidationReport:
        """Validate a contract using the standard validator."""
        return self.validator.validate(contract)

    def evaluate_policy(
        self,
        base_contract: OpenDataContractStandard,
        merged_contract: OpenDataContractStandard,
    ) -> PolicyEvaluation:
        """Evaluate lifecycle policy constraints between base and merged contracts."""
        return evaluate_merge_policy(base_contract, merged_contract)

    def prepare_ci_cd_artifacts(
        self,
        merged_contract: OpenDataContractStandard,
        merge_result: MergeResult,
        decision: GovernanceDecision,
        *,
        merged_contract_output_path: str,
        ge_suite_output_path: str,
        ci_manifest_output_path: str,
        ge_schema_name: str = "all",
        ge_suite_name: str | None = None,
        audit_metadata: AuditMetadata | None = None,
    ) -> PipelineArtifacts:
        """Write the merged contract and downstream CI/CD artifacts to disk."""
        if not isinstance(decision, GovernanceDecision):
            raise TypeError(f"prepare_ci_cd_artifacts requires GovernanceDecision, got {type(decision).__name__}")

        merged_contract_path = dump_yaml(
            contract_to_dict(merged_contract), merged_contract_output_path
        )
        ge_suite_path = self.ge_exporter.export_to_path(
            merged_contract,
            ge_suite_output_path,
            schema_name=ge_schema_name,
            suite_name=ge_suite_name,
        )

        ci_manifest_path = Path(ci_manifest_output_path).expanduser().resolve()
        ci_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "governanceDecision": decision.to_dict(),
            "valid": decision.validation.valid,
            "policyValid": decision.policy.valid,
            "idViolation": decision.policy.id_violation,
            "versionViolation": decision.policy.version_violation,
            "issues": [asdict(issue) for issue in decision.validation.issues],
            "breakingChanges": [v.to_dict() for v in decision.policy.violations if v.code == "POLICY_BREAKING_CHANGE"],
            "conflicts": [asdict(conflict) for conflict in merge_result.conflicts],
            "artifacts": {
                "mergedContract": str(merged_contract_path),
                "greatExpectationsSuite": str(ge_suite_path),
            },
            "audit": asdict(audit_metadata) if audit_metadata is not None else None,
        }
        ci_manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )

        return PipelineArtifacts(
            merged_contract_path=merged_contract_path,
            ge_suite_path=ge_suite_path,
            ci_manifest_path=ci_manifest_path,
        )

    def run(
        self,
        *,
        source_type: ImportSourceType,
        source: str,
        business_contract_path: str,
        merged_contract_output_path: str,
        ge_suite_output_path: str,
        ci_manifest_output_path: str,
        fail_on_conflict: bool = False,
        uc_workspace_url: str | None = None,
        uc_token: str | None = None,
        ge_schema_name: str = "all",
        ge_suite_name: str | None = None,
        audit_metadata: AuditMetadata | None = None,
    ) -> PipelineArtifacts:
        """Execute the full SemaPact automation pipeline end to end."""
        imported_contract = self.import_schema(
            source_type,
            source,
            uc_workspace_url=uc_workspace_url,
            uc_token=uc_token,
        )
        business_contract = self.loader.load(business_contract_path)

        # Handle retired base contract: evaluate before merge, write decision manifest, raise GovernanceBlockedError
        if self._resolve_lifecycle(business_contract) == "retired":
            decision = evaluate_governance_decision(business_contract, imported_contract)
            manifest_path = write_decision_manifest(
                decision, ci_manifest_output_path, audit_metadata=audit_metadata
            )
            raise GovernanceBlockedError(
                f"Cannot run pipeline on retired contract: {decision.reasons}",
                decision=decision,
                manifest_path=manifest_path,
            )

        # Merge updates with fail_on_conflict=False so governance decision evaluates all conflicts and changes
        merge_result = self.merge_contract_updates(
            imported_contract,
            business_contract,
            fail_on_conflict=False,
        )
        if merge_result.contract is None:
            raise ValueError("Merge did not produce a contract")

        # Single-pass governance decision evaluation
        decision = evaluate_governance_decision(
            business_contract,
            merge_result.contract,
            merge_conflicts=merge_result.conflicts,
        )

        # BLOCK Decision: Write decision-only manifest FIRST, skipping GE/YAML export, then raise GovernanceBlockedError
        if decision.decision == DecisionResult.BLOCK:
            manifest_path = write_decision_manifest(
                decision, ci_manifest_output_path, audit_metadata=audit_metadata
            )
            reasons_text = "; ".join(f"{r.path or 'root'}: {r.message}" for r in decision.reasons) or "Governance decision BLOCKED"
            raise GovernanceBlockedError(
                f"Governance decision BLOCKED: {reasons_text}",
                decision=decision,
                manifest_path=manifest_path,
            )

        # Handle fail_on_conflict: Write decision manifest FIRST, then raise ValueError
        if merge_result.conflicts and fail_on_conflict:
            write_decision_manifest(
                decision, ci_manifest_output_path, audit_metadata=audit_metadata
            )
            message = "; ".join(
                f"{c.schema_id}.{c.property_name}: {c.message}"
                for c in merge_result.conflicts
            )
            raise ValueError(f"Merge conflicts detected: {message}")

        # ALLOW or REVIEW: Write artifacts and manifest
        artifacts = self.prepare_ci_cd_artifacts(
            merge_result.contract,
            merge_result,
            decision,
            merged_contract_output_path=merged_contract_output_path,
            ge_suite_output_path=ge_suite_output_path,
            ci_manifest_output_path=ci_manifest_output_path,
            ge_schema_name=ge_schema_name,
            ge_suite_name=ge_suite_name,
            audit_metadata=audit_metadata,
        )

        return artifacts

    def _resolve_lifecycle(self, contract: OpenDataContractStandard) -> str:
        """Resolve lifecycle status from status or customProperties fallback."""
        value = (contract.status or "").strip().lower()
        if value:
            return value
        for item in contract.customProperties or []:
            key = (item.property or "").strip().lower()
            if key != "lifecyclestatus":
                continue
            resolved = (
                (str(item.value) if item.value is not None else "").strip().lower()
            )
            return resolved or "draft"
        return "draft"
