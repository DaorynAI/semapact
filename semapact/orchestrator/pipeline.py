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
        """Import a technical contract from a supported source type.

        This step creates the "source" side of the merge:
        the latest contract representation generated from a system of record
        such as SQL DDL, Delta metadata, or Unity Catalog metadata.

        If `existing_contract` is provided, the importer result is immediately
        merged against it using the merge engine. This is mainly useful for
        importer-driven patch/update scenarios.
        """
        import_args = import_args or {}
        normalized = source_type.strip().lower()

        if normalized in {"uc", "unity"}:
            return import_unity_contract(
                table_fqn=source,
                workspace_url=uc_workspace_url,
                token=uc_token,
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
        imported_contract: OpenDataContractStandard,
        business_contract: OpenDataContractStandard,
        *,
        fail_on_conflict: bool = False,
    ) -> MergeResult:
        """Merge imported technical updates into the governed target contract.

        Terminology:
        - `imported_contract`: newly generated technical/source contract
        - `business_contract`: lifecycle-governed target contract from Git

        The merge engine preserves governed metadata while applying technical
        schema updates and lifecycle rules.
        """
        # `business_contract` is the lifecycle-governed target contract in Git.
        target_contract = business_contract
        return self.merge_engine.merge(
            imported_contract,
            target_contract,
            fail_on_conflict=fail_on_conflict,
        )

    def validate_contract(self, contract: OpenDataContractStandard) -> ValidationReport:
        """Run contract-level structural and quality-rule validation."""
        return self.validator.validate(contract)

    def evaluate_policy(
        self,
        base_contract: OpenDataContractStandard,
        merged_contract: OpenDataContractStandard,
    ) -> PolicyEvaluation:
        """Evaluate lifecycle policy on the merged contract result.

        Current root-level governance rules:
        - contract `id` is immutable after the governed contract is created
        - contract `version` is release-managed and must not change in the
          normal import/merge pipeline
        """
        return evaluate_merge_policy(base_contract, merged_contract)

    def prepare_ci_cd_artifacts(
        self,
        merged_contract: OpenDataContractStandard,
        merge_result: MergeResult,
        validation: ValidationReport,
        policy_evaluation: PolicyEvaluation,
        *,
        merged_contract_output_path: str,
        ge_suite_output_path: str,
        ci_manifest_output_path: str,
        ge_schema_name: str = "all",
        ge_suite_name: str | None = None,
        audit_metadata: AuditMetadata | None = None,
    ) -> PipelineArtifacts:
        """Write the merged contract and downstream CI/CD artifacts to disk.

        Artifacts currently include:
        - merged contract YAML
        - Great Expectations suite JSON
        - CI manifest summarizing validation, policy, conflicts, and outputs
        """
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
            "valid": validation.valid,
            "policyValid": policy_evaluation.valid,
            "idViolation": policy_evaluation.id_violation,
            "versionViolation": policy_evaluation.version_violation,
            "issues": [asdict(issue) for issue in validation.issues],
            "breakingChanges": [
                asdict(change) for change in policy_evaluation.breaking_changes
            ],
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
        """Execute the full SemaPact automation pipeline end to end.

        Execution order:
        1. import technical/source contract
        2. load existing governed contract
        3. block execution for retired contracts
        4. merge imported updates into the governed contract
        5. validate merged contract structure and rule completeness
        6. evaluate lifecycle policy/version constraints
        7. write merged contract + artifact outputs

        This is the main API for CI/CD or scheduled automation jobs.
        """
        imported_contract = self.import_schema(
            source_type,
            source,
            uc_workspace_url=uc_workspace_url,
            uc_token=uc_token,
        )
        business_contract = self.loader.load(business_contract_path)
        if self._resolve_lifecycle(business_contract) == "retired":
            raise ValueError("Cannot run pipeline on retired contract")

        merge_result = self.merge_contract_updates(
            imported_contract,
            business_contract,
            fail_on_conflict=fail_on_conflict,
        )
        if merge_result.conflicts and fail_on_conflict:
            message = "; ".join(
                f"{c.schema_id}.{c.property_name}: {c.message}"
                for c in merge_result.conflicts
            )
            raise ValueError(f"Merge conflicts detected: {message}")
        if merge_result.contract is None:
            raise ValueError("Merge did not produce a contract")

        validation = self.validate_contract(merge_result.contract)
        if not validation.valid:
            message = "; ".join(
                f"{item.path}: {item.message}" for item in validation.issues
            )
            raise ValueError(f"Merged contract validation failed: {message}")

        policy_evaluation = self.evaluate_policy(
            business_contract, merge_result.contract
        )
        id_violation = getattr(policy_evaluation, "id_violation", False)
        version_violation = getattr(policy_evaluation, "version_violation", False)
        if not policy_evaluation.valid and (id_violation or version_violation):
            violations = [
                item
                for item in policy_evaluation.breaking_changes
                if item.path in ("id", "version")
            ]
            message = "; ".join(f"❌ {item.message}" for item in violations)
            raise ValueError(f"Policy Violation:\n{message}")

        return self.prepare_ci_cd_artifacts(
            merge_result.contract,
            merge_result,
            validation,
            policy_evaluation,
            merged_contract_output_path=merged_contract_output_path,
            ge_suite_output_path=ge_suite_output_path,
            ci_manifest_output_path=ci_manifest_output_path,
            ge_schema_name=ge_schema_name,
            ge_suite_name=ge_suite_name,
            audit_metadata=audit_metadata,
        )

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
