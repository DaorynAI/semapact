"""SemaPact enterprise library.

The package root intentionally lazy-loads public exports so installing one
optional platform capability does not import unrelated platform dependencies.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, tuple[str, str]] = {
    "ApprovalRecord": ("semapact.approval", "ApprovalRecord"),
    "ApprovalRecordService": (
        "semapact.application.services.approval_record",
        "ApprovalRecordService",
    ),
    "ContractLoader": ("semapact.core.loader", "ContractLoader"),
    "load_contract": ("semapact.core.loader", "load_contract"),
    "ContractValidator": ("semapact.core.validator", "ContractValidator"),
    "AzureDevOpsConfig": ("semapact.devops.pr_creator", "AzureDevOpsConfig"),
    "PullRequestCreator": ("semapact.devops.pr_creator", "PullRequestCreator"),
    "SparkSqlContractExporter": (
        "semapact.exporters.sql_exporter",
        "SparkSqlContractExporter",
    ),
    "export_contract_to_spark_sql": (
        "semapact.exporters.sql_exporter",
        "export_contract_to_spark_sql",
    ),
    "DeltaTableImporter": ("semapact.importers.delta_importer", "DeltaTableImporter"),
    "SQLFolderImporter": ("semapact.importers.sql_importer", "SQLFolderImporter"),
    "ContractMergeEngine": ("semapact.lifecycle.merge_engine", "ContractMergeEngine"),
    "evaluate_merge_policy": ("semapact.lifecycle.policy", "evaluate_merge_policy"),
    "ContractPipeline": ("semapact.orchestrator.pipeline", "ContractPipeline"),
    "GreatExpectationsExporter": (
        "semapact.quality.ge_exporter",
        "GreatExpectationsExporter",
    ),
    "run_contract_tests": ("semapact.quality.validation", "run_contract_tests"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve public exports only when callers actually request them."""
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute = target
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Include lazy public exports in interactive discovery."""
    return sorted({*globals(), *__all__})
