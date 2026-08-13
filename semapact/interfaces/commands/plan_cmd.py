import argparse
from typing import Any
from semapact.governance import (
    GovernanceOperation,
    evaluate_governance_decision,
    evaluate_governance_gate,
)
from semapact.interfaces.commands.utils import _resolve_adls_oauth_token_from_config, _parse_table_uris

def run_plan(args: argparse.Namespace) -> None:
    from semapact.orchestrator.pipeline import ContractPipeline

    pipeline = ContractPipeline()

    print(f"\n🔍 Contract Analysis: {args.base}")

    try:
        import_args: dict[str, Any] = {}
        if args.type in {"delta", "delta-table"}:
            oauth_token = None
            if args.source.startswith("abfss://") or "dfs.core.windows.net" in args.source:
                oauth_token = _resolve_adls_oauth_token_from_config()
                
            table_uris = _parse_table_uris(args.tables)
            if not table_uris:
                from semapact.utils.storage_adapter import StorageAdapterFactory
                adapter = StorageAdapterFactory.get_adapter(args.source)
                try:
                    table_uris = adapter.discover_delta_tables(args.source, credential=oauth_token)
                except Exception as e:
                    import logging
                    logging.getLogger("semapact").warning(f"Failed to auto-discover delta tables: {e}")
                    table_uris = []
            
            if oauth_token:
                import_args["oauth_bearer_token"] = oauth_token
            if table_uris:
                import_args["table_uris"] = table_uris
        elif args.tables:
            import_args["tables"] = args.tables

        # Import temporary contract from source
        imported = pipeline.import_schema(
            source_type=args.type,
            source=args.source,
            uc_workspace_url=args.workspace_url,
            uc_token=args.token,
            import_args=import_args if import_args else None,
        )

        # Load base contract (governed target)
        base_contract = pipeline.loader.load(args.base)

        # Merge them (to normalize and evaluate breaks)
        merge_result = pipeline.merge_contract_updates(
            imported, base_contract, fail_on_conflict=False
        )
        merged = merge_result.contract

        # Evaluate decision & ANALYZE operation gate (always allowed for analysis)
        decision = evaluate_governance_decision(
            base_contract, merged, merge_conflicts=merge_result.conflicts
        )
        gate_res = evaluate_governance_gate(decision, GovernanceOperation.ANALYZE)

        if not decision.evidence.has_changes:
            print("🟢 No changes detected.")
        else:
            print(f"📊 Governance Decision: {decision.decision.value} (Gate: {gate_res.reason})")
            for reason in decision.reasons:
                print(f"  • [{reason.code}] {reason.path or 'root'}: {reason.message}")

            bump = decision.required_version_bump.upper()
            if bump == "NONE":
                print("\n✅ Action Required: No version bump needed.")
            elif bump == "MINOR":
                print(f"\n⚠️ Action Required: Additive changes require version bump {bump}.")
            elif bump == "MAJOR":
                print(f"\n⚠️ Action Required: Breaking changes require version bump {bump}.")

    except Exception as e:
        from semapact.exceptions import SemaPactError
        import logging

        if isinstance(e, SemaPactError):
            logging.getLogger("semapact").error("Plan failed: %s", e)
        else:
            logging.getLogger("semapact").error("Plan failed: %s", e, exc_info=True)
        print(f"❌ Error during plan: {e}")
        raise SystemExit(1)
