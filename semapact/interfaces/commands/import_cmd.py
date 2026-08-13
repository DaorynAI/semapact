import argparse
import logging
from pathlib import Path
from typing import Any

from semapact.core.plugin_registry import PluginRegistry
from semapact.governance import GovernanceOperation, enforce_governance_gate
from semapact.interfaces.commands.utils import (
    _parse_table_uris,
    _resolve_adls_oauth_token_from_config,
)
from semapact.services import GovernanceService

def run_import(args: argparse.Namespace) -> Path:
    from semapact.core.loader import ContractLoader
    from datacontract.data_contract import DataContract
    from semapact.importers.unity_importer import import_unity_contract
    from semapact.utils.schema_utils import contract_to_dict
    from semapact.utils.yaml_utils import dump_yaml

    loader = ContractLoader(runtime_context=args.runtime_context)
    existing_contract: Any | None = None
    if getattr(args, "existing", None):
        existing_contract = loader.load(args.existing)

    if args.format in {"delta", "delta-table"}:
        oauth_token = None
        if args.source.startswith("abfss://") or "dfs.core.windows.net" in args.source:
            oauth_token = _resolve_adls_oauth_token_from_config()
            
        table_uris = getattr(args, "tables", None)
        table_uris = _parse_table_uris(table_uris)
        
        # If no explicit tables are provided, use StorageAdapter to discover them
        if not table_uris:
            from semapact.utils.storage_adapter import StorageAdapterFactory
            adapter = StorageAdapterFactory.get_adapter(args.source)
            try:
                table_uris = adapter.discover_delta_tables(args.source, credential=oauth_token)
            except Exception as e:
                logging.getLogger("semapact").warning(f"Failed to auto-discover delta tables: {e}")
                table_uris = []
                
        contract = DataContract.import_from_source(
            format="delta",
            source=args.source,
            oauth_bearer_token=oauth_token,
            table_uris=table_uris,
        )
    elif args.format == "delta-ddl":
        contract = DataContract.import_from_source(
            format="delta-ddl",
            source=args.source,
        )
    elif args.format in {"sql", "sql-folder"}:
        contract = DataContract.import_from_source(
            format=args.format,
            source=args.source,
        )
    elif args.format in {"uc", "unity"}:
        contract = import_unity_contract(
            table_fqn=args.source,
            workspace_url=args.workspace_url,
            token=args.token,
            sql_http_path=args.sql_http_path,
            extract_lineage=args.extract_lineage,
        )
    else:
        # Pass-through for custom formats/plugins
        contract = DataContract.import_from_source(
            format=args.format,
            source=args.source,
        )

    if existing_contract is not None:
        analysis = GovernanceService().merge_and_evaluate(
            contract,
            existing_contract,
            effective_date=args.effective_date,
        )
        contract = analysis.merge_result.contract
        enforce_governance_gate(analysis.decision, GovernanceOperation.PROPOSE)

    # Allow plugins to redirect output routing before write (only executed after gate passes).
    # Pass deepcopy of contract so post-gate hooks cannot mutate the validated contract.
    from copy import deepcopy

    hook_result = PluginRegistry.execute_hook(
        "on_import_complete",
        contract=deepcopy(contract),
        format=args.format,
        source=args.source,
        args=args,
    )

    output_path = hook_result if hook_result else args.output
    return dump_yaml(contract_to_dict(contract), output_path)
