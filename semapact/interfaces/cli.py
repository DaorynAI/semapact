from __future__ import annotations

import argparse
import json
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    pass


def _add_effective_date_argument(
    parser: argparse.ArgumentParser,
    *,
    required: bool = True,
) -> None:
    parser.add_argument(
        "--effective-date",
        required=required,
        help="Governance effective date in YYYY-MM-DD format",
    )


def _build_parser() -> argparse.ArgumentParser:
    from semapact.contractops import ReviewEvidenceAction
    from semapact.governance import GovernanceOperation

    parser = argparse.ArgumentParser(prog="semapact")
    subparsers = parser.add_subparsers(dest="command", required=False)

    subparsers.add_parser(
        "tui", help="Launch the interactive Terminal User Interface (k9s style)"
    )

    init_parser = subparsers.add_parser(
        "init", help="Initialize configuration and optionally bootstrap repository templates"
    )
    init_parser.add_argument(
        "--scaffold", action="store_true", help="Bootstrap repository with GitOps templates and CI pipelines"
    )

    lifecycle_parser = subparsers.add_parser(
        "lifecycle", help="Manage contract, schema, or property lifecycle status"
    )
    lifecycle_subparsers = lifecycle_parser.add_subparsers(
        dest="lifecycle_command", required=True
    )

    promote_parser = lifecycle_subparsers.add_parser(
        "promote", help="Promote entity to active status"
    )
    promote_parser.add_argument("--runtime-context", default=None)
    promote_parser.add_argument(
        "--contract", required=True, help="Path to the YAML contract"
    )
    promote_parser.add_argument("--schema", help="Target schema name")
    promote_parser.add_argument("--property", help="Target property name")
    promote_parser.add_argument(
        "--output", help="Output path (defaults to overwriting contract)"
    )
    _add_effective_date_argument(promote_parser)

    deprecate_parser = lifecycle_subparsers.add_parser(
        "deprecate", help="Deprecate entity status"
    )
    deprecate_parser.add_argument("--runtime-context", default=None)
    deprecate_parser.add_argument(
        "--contract", required=True, help="Path to the YAML contract"
    )
    deprecate_parser.add_argument("--schema", help="Target schema name")
    deprecate_parser.add_argument("--property", help="Target property name")
    deprecate_parser.add_argument(
        "--output", help="Output path (defaults to overwriting contract)"
    )
    _add_effective_date_argument(deprecate_parser)

    enrich_parser = subparsers.add_parser(
        "enrich", 
        help="Enrich data contract with semantic relationship labels via LLM. Note: This will not overwrite existing human-annotated data."
    )
    enrich_parser.add_argument(
        "--contract", required=True, help="Path to the YAML contract"
    )
    enrich_parser.add_argument(
        "--concurrency", type=int, default=1, help="Max parallel LLM API calls"
    )
    enrich_parser.add_argument(
        "--mode",
        choices=[
            "label",
            "infer_joins",
            "describe_tables",
            "describe_columns",
            "suggest_quality",
        ],
        default="label",
        help="Enrichment mode: 'label' for tagging existing relationships, 'infer_joins' for discovering new semantic relationships, 'describe_tables' for missing table descriptions, 'describe_columns' for missing column descriptions, 'suggest_quality' for generating DataQuality rules.",
    )
    enrich_parser.add_argument(
        "--system-prompt", help="Override the system prompt template sent to the LLM"
    )
    enrich_parser.add_argument(
        "--user-prompt", help="Override the user prompt template sent to the LLM"
    )

    plan_parser = subparsers.add_parser(
        "plan", help="Dry run and summarize changes between source and base contract"
    )
    plan_parser.add_argument("--source", required=True)
    plan_parser.add_argument("--base", required=True)
    plan_parser.add_argument(
        "--type", required=True, help="The source type (e.g. delta, sql, uc, controldb)"
    )
    _add_effective_date_argument(plan_parser)
    
    plan_delta_group = plan_parser.add_argument_group("Delta Import Options")
    plan_delta_group.add_argument("--tables")
    
    plan_unity_group = plan_parser.add_argument_group("Unity Catalog Options")
    plan_unity_group.add_argument("--workspace-url")
    plan_unity_group.add_argument("--token")

    import_parser = subparsers.add_parser("import", help="Import contract from source")
    import_parser.add_argument(
        "--format",
        required=True,
        help="The source format (e.g. delta, sql, uc, controldb)"
    )
    import_parser.add_argument("--source", required=True)
    import_parser.add_argument("--output", required=True)
    import_parser.add_argument("--existing")
    import_parser.add_argument("--runtime-context", default="auto")
    _add_effective_date_argument(import_parser, required=False)

    import_delta_group = import_parser.add_argument_group("Delta Import Options")
    import_delta_group.add_argument(
        "--tables",
        help="Comma-separated list of additional Delta table URIs (used with --format delta or --format delta-table)",
    )

    import_unity_group = import_parser.add_argument_group("Unity Catalog Options")
    import_unity_group.add_argument("--workspace-url")
    import_unity_group.add_argument("--token")
    import_unity_group.add_argument("--sql-http-path")
    import_unity_group.add_argument(
        "--extract-lineage",
        action="store_true",
        help="Attempt to extract column-level lineage and logic from source (only supported for uc/unity format)",
    )

    merge_parser = subparsers.add_parser(
        "merge", help="Merge base and business-edited contracts"
    )
    merge_parser.add_argument("--base", required=True)
    merge_parser.add_argument("--business", required=True)
    merge_parser.add_argument("--output", required=True)
    merge_parser.add_argument("--runtime-context", default="auto")
    _add_effective_date_argument(merge_parser)

    export_parser = subparsers.add_parser(
        "export", help="Convert data contract to a specific format"
    )
    export_parser.add_argument(
        "location",
        nargs="?",
        default="datacontract.yaml",
        help="The location (url or path) of the data contract yaml",
    )
    export_parser.add_argument(
        "--format",
        required=True,
        help="The export format (e.g. html, graph, jsonschema, dbt, etc.)",
    )
    export_parser.add_argument(
        "--output",
        help="Specify the file path where the exported data will be saved. If no path is provided, the output will be printed to stdout.",
    )
    
    export_advanced_group = export_parser.add_argument_group("Advanced Export Options")
    export_advanced_group.add_argument("--server", help="The server name to export.")
    export_advanced_group.add_argument(
        "--schema-name",
        default="all",
        help="The name of the schema to export, e.g., orders, or all for all schemas (default).",
    )
    export_advanced_group.add_argument(
        "--sql-server-type",
        default="auto",
        help="The server type to determine the sql dialect.",
    )
    export_advanced_group.add_argument(
        "--export-args",
        help='Additional arguments for custom exporters in JSON string format, e.g. \'{"format": "cypher"}\'',
    )

    ge_parser = subparsers.add_parser(
        "export-ge", help="Export Great Expectations suite"
    )
    ge_parser.add_argument("--contract", required=True)
    ge_parser.add_argument("--output", required=True)
    ge_parser.add_argument("--schema-name", default="all")
    ge_parser.add_argument("--suite-name")
    ge_parser.add_argument("--engine", choices=["spark", "pandas"], default="pandas", help="Validation engine for Great Expectations")

    pr_parser = subparsers.add_parser("create-pr", help="Create Azure DevOps PR")
    pr_parser.add_argument(
        "--git-provider",
        choices=["azure", "github"],
    )
    pr_parser.add_argument("--organization")
    pr_parser.add_argument("--github-owner")
    pr_parser.add_argument("--github-repo")
    pr_parser.add_argument("--github-token")
    pr_parser.add_argument("--project")
    pr_parser.add_argument("--repository-id")
    pr_parser.add_argument("--pat-token")
    pr_parser.add_argument("--repo-path", help="Local repository path")
    pr_parser.add_argument("--source-branch", required=True)
    pr_parser.add_argument("--target-branch", required=True)
    pr_parser.add_argument("--commit-message", required=True)
    pr_parser.add_argument("--title", required=True)
    pr_parser.add_argument("--description", required=True)
    pr_parser.add_argument("--paths", nargs="*")
    pr_parser.add_argument("--push", action="store_true")

    approval_parser = subparsers.add_parser(
        "approval",
        help="Record explicit governance review evidence",
    )
    approval_subparsers = approval_parser.add_subparsers(
        dest="approval_command", required=True
    )
    approval_record_parser = approval_subparsers.add_parser(
        "record",
        help="Persist one explicit external review event as immutable approval history",
    )
    approval_record_parser.add_argument(
        "--repository-root",
        default=".",
        help="Repository root containing .semapact/history (default: current directory)",
    )
    approval_record_parser.add_argument("--decision-id", required=True)
    approval_record_parser.add_argument("--change-set-id", required=True)
    approval_record_parser.add_argument("--release-plan-id", required=True)
    approval_record_parser.add_argument("--version-resolution-id", required=True)
    approval_record_parser.add_argument(
        "--operation",
        required=True,
        choices=[item.value for item in GovernanceOperation],
    )
    approval_record_parser.add_argument(
        "--action",
        required=True,
        choices=[item.value for item in ReviewEvidenceAction],
    )
    approval_record_parser.add_argument("--actor-reference", required=True)
    approval_record_parser.add_argument(
        "--recorded-at",
        required=True,
        help="Timezone-aware ISO-8601 timestamp from the external review event",
    )
    approval_record_parser.add_argument("--scope-reference")
    approval_record_parser.add_argument("--capability-reference")
    approval_record_parser.add_argument("--comment")
    approval_record_parser.add_argument(
        "--evidence-reference",
        action="append",
        help="Stable external review evidence reference; may be provided multiple times",
    )

    release_parser = subparsers.add_parser(
        "release", help="Per-contract release workflow helpers"
    )
    release_subparsers = release_parser.add_subparsers(
        dest="release_command", required=True
    )

    release_assess_parser = release_subparsers.add_parser(
        "assess",
        help="Build one immutable target-neutral formal ReleaseBundle",
    )
    release_assess_parser.add_argument("--base", required=True)
    release_assess_parser.add_argument("--candidate", required=True)
    release_assess_parser.add_argument("--base-revision-ref", required=True)
    release_assess_parser.add_argument("--candidate-revision-ref", required=True)
    release_assess_parser.add_argument(
        "--authority-reference",
        help="Explicit Git release reference when release.versionAuthority=git",
    )
    release_assess_parser.add_argument("--runtime-context", default="auto")
    release_assess_parser.add_argument(
        "--bundle-out",
        help="Write the immutable ReleaseBundle JSON artifact to this path",
    )

    release_approve_parser = release_subparsers.add_parser(
        "approve",
        help="Record explicit REVIEW approval for one exact ReleaseBundle",
    )
    release_approve_parser.add_argument("--bundle", required=True)
    release_approve_parser.add_argument("--actor-reference", required=True)
    release_approve_parser.add_argument(
        "--recorded-at",
        required=True,
        help="Approval timestamp as timezone-aware ISO-8601",
    )
    release_approve_parser.add_argument("--comment")
    release_approve_parser.add_argument(
        "--repository-root",
        default=".",
        help="Repository root containing the Git governance ledger",
    )
    release_approve_parser.add_argument(
        "--approval-out",
        help="Optional standalone ApprovalRecord JSON output",
    )

    release_finalize_parser = release_subparsers.add_parser(
        "finalize",
        help="Finalize one ReleaseBundle, record it, and materialize the versioned contract",
    )
    release_finalize_parser.add_argument("--bundle", required=True)
    release_finalize_parser.add_argument(
        "--approval",
        help=(
            "Exact ApprovalRecord JSON artifact for a REVIEW release. "
            "When omitted, SemaPact may resolve approval from the Git governance ledger."
        ),
    )
    release_finalize_parser.add_argument(
        "--output-contract",
        required=True,
        help="Write the exact released/versioned ODCS contract to this path",
    )
    release_finalize_parser.add_argument(
        "--release-out",
        help="Write the finalized immutable ContractRelease JSON artifact to this path",
    )
    release_finalize_parser.add_argument(
        "--repository-root",
        default=".",
        help="Repository root containing the Git governance ledger",
    )

    release_classify_parser = release_subparsers.add_parser(
        "classify",
        help="Analyze the required version bump without creating release artifacts",
    )
    release_classify_parser.add_argument("--base", required=True)
    release_classify_parser.add_argument("--candidate", required=True)
    release_classify_parser.add_argument("--runtime-context", default="auto")

    release_plan_parser = release_subparsers.add_parser(
        "plan",
        help="Build canonical ChangeSet, ReleasePlan, and VersionResolution artifacts",
    )
    release_plan_parser.add_argument("--base", required=True)
    release_plan_parser.add_argument("--candidate", required=True)
    release_plan_parser.add_argument("--base-revision-ref", required=True)
    release_plan_parser.add_argument("--candidate-revision-ref", required=True)
    release_plan_parser.add_argument(
        "--authority-reference",
        help="Explicit Git release reference when release.versionAuthority=git",
    )
    release_plan_parser.add_argument("--runtime-context", default="auto")

    release_classify_repo_parser = release_subparsers.add_parser(
        "classify-repo",
        help="Classify per-contract required bumps across two contract roots",
    )
    release_classify_repo_parser.add_argument("--base-root", required=True)
    release_classify_repo_parser.add_argument("--candidate-root", required=True)


    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check production prerequisites for the contract-selected runtime",
    )
    doctor_parser.add_argument(
        "--contract", required=True, help="Path or URL to the governed ODCS contract"
    )
    doctor_parser.add_argument(
        "--server",
        help="Contract server identifier when the contract defines multiple servers",
    )
    doctor_parser.add_argument(
        "--platform",
        help="Fallback runtime provider when the contract defines no servers",
    )
    doctor_parser.add_argument(
        "--runtime",
        help="Fallback provider-local runtime target when the contract defines no servers",
    )
    doctor_parser.add_argument(
        "--warehouse-id",
        help="Databricks SQL warehouse used for read-only Statement Execution readiness checks",
    )
    doctor_parser.add_argument(
        "--repository-root",
        default=".",
        help="Repository root containing governance history (default: current directory)",
    )
    doctor_parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    reconcile_parser = subparsers.add_parser(
        "reconcile",
        help="Compare a governed data product with its runtime implementation",
    )
    reconcile_parser.add_argument(
        "--contract", required=True, help="Path or URL to the governed ODCS contract"
    )
    reconcile_parser.add_argument(
        "--server",
        help="Contract server identifier when the contract defines multiple servers",
    )
    reconcile_parser.add_argument(
        "--platform",
        help="Fallback runtime provider when the contract defines no servers",
    )
    reconcile_parser.add_argument(
        "--runtime",
        help="Fallback provider-local runtime product target when the contract defines no servers",
    )
    reconcile_parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    deployment_parser = subparsers.add_parser(
        "deployment",
        help="Assess and deploy immutable target-specific runtime bundles",
    )
    deployment_subparsers = deployment_parser.add_subparsers(
        dest="deployment_command", required=True
    )

    deployment_assess_parser = deployment_subparsers.add_parser(
        "assess",
        help=(
            "Assess either a base/candidate change or an already-finalized release "
            "against one fresh runtime target"
        ),
    )
    deployment_assess_parser.add_argument("--base")
    deployment_assess_parser.add_argument("--candidate")
    deployment_assess_parser.add_argument("--base-revision-ref")
    deployment_assess_parser.add_argument("--candidate-revision-ref")
    release_source_group = deployment_assess_parser.add_mutually_exclusive_group()
    release_source_group.add_argument(
        "--release",
        help="Finalized ContractRelease JSON artifact to deploy instead of a candidate",
    )
    release_source_group.add_argument(
        "--release-id",
        help="Convenience fallback: resolve a finalized ContractRelease ID from Git history",
    )
    deployment_assess_parser.add_argument(
        "--repository-root",
        default=".",
        help="Repository root containing finalized release history",
    )
    deployment_assess_parser.add_argument(
        "--server",
        help="Contract server identifier when the deployment source defines multiple servers",
    )
    deployment_assess_parser.add_argument(
        "--platform",
        help="Fallback runtime provider when the deployment source defines no servers",
    )
    deployment_assess_parser.add_argument(
        "--runtime",
        help="Fallback provider-local runtime target when the deployment source defines no servers",
    )
    deployment_assess_parser.add_argument(
        "--source-reference",
        help="Fallback stable runtime source identity when the source defines no server host",
    )
    deployment_assess_parser.add_argument("--runtime-context", default="auto")
    deployment_assess_parser.add_argument(
        "--bundle-out",
        help="Write the immutable DeploymentBundle JSON artifact to this path",
    )
    deployment_assess_parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    deployment_deploy_parser = deployment_subparsers.add_parser(
        "deploy",
        help="Consume an immutable DeploymentBundle, execute against fresh runtime, and verify",
    )
    deployment_deploy_parser.add_argument("--bundle", required=True)
    deployment_deploy_parser.add_argument(
        "--warehouse-id",
        help=(
            "Databricks SQL warehouse required for runtime mutation and formal-release "
            "Unity Catalog provenance tag projection"
        ),
    )
    deployment_deploy_parser.add_argument(
        "--operational-history",
        help=(
            "Optional operational-history URI override. When omitted, SemaPact reads "
            "typed history.operational configuration; if neither is configured, "
            "deployment telemetry persistence is disabled."
        ),
    )
    deployment_deploy_parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )


    return parser


def main() -> int:
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = _build_parser()
    try:
        args = parser.parse_args()
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    if not args.command:
        parser.print_help()
        return 0

    try:
        if args.command == "tui":
            try:
                import textual  # noqa: F401
            except ImportError:
                import sys
                print("❌ TUI requires the 'tui' extra. Install it via: pip install \"semapact[tui]\"", file=sys.stderr)
                from semapact.interfaces.outcomes import CliExitCode
                return int(CliExitCode.RUNTIME_ERROR)
            from semapact.tui.app import SemaPactTUI
            app = SemaPactTUI()
            app.run()
            return 0

        if args.command == "init":
            from semapact.interfaces.commands.init_cmd import run_init
            run_init(args)
            return 0

        if args.command == "lifecycle":
            from semapact.interfaces.commands.lifecycle_cmd import run_lifecycle_promote, run_lifecycle_deprecate
            if args.lifecycle_command == "promote":
                payload = run_lifecycle_promote(args)
                print(json.dumps(payload, indent=2, sort_keys=True))
                return 0
            if args.lifecycle_command == "deprecate":
                payload = run_lifecycle_deprecate(args)
                print(json.dumps(payload, indent=2, sort_keys=True))
                return 0

        if args.command == "enrich":
            from semapact.interfaces.commands.enrich_cmd import run_enrich
            output = run_enrich(args)
            print(output)
            return 0

        if args.command == "plan":
            from semapact.interfaces.commands.plan_cmd import run_plan
            run_plan(args)
            return 0

        if args.command == "import":
            from semapact.interfaces.commands.import_cmd import run_import
            output = run_import(args)
            print(output)
            return 0

        if args.command == "export":
            from semapact.interfaces.commands.export_cmd import run_export
            output = run_export(args)
            print(output)
            return 0

        if args.command == "merge":
            from semapact.interfaces.commands.merge_cmd import run_merge
            output = run_merge(args)
            print(output)
            return 0

        if args.command == "export-ge":
            from semapact.interfaces.commands.export_cmd import run_export_ge
            output = run_export_ge(args)
            print(output)
            return 0

        if args.command == "create-pr":
            from semapact.interfaces.commands.pr_cmd import run_create_pr
            payload = run_create_pr(args)
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0

        if args.command == "approval":
            from semapact.interfaces.commands.approval_cmd import run_approval_record

            if args.approval_command == "record":
                payload = run_approval_record(args)
                print(json.dumps(payload, indent=2, sort_keys=True))
                return 0
            parser.error(f"Unknown approval command: {args.approval_command}")


        if args.command == "doctor":
            from semapact.interfaces.commands.doctor_cmd import run_doctor
            from semapact.interfaces.outcomes import exit_code_from_outcome

            result = run_doctor(args)
            print(result.output)
            return int(exit_code_from_outcome(result.outcome))

        if args.command == "reconcile":
            from semapact.interfaces.commands.reconcile_cmd import run_reconcile
            from semapact.interfaces.outcomes import exit_code_from_outcome

            result = run_reconcile(args)
            print(result.output)
            return int(exit_code_from_outcome(result.outcome))

        if args.command == "deployment":
            from semapact.interfaces.commands.deployment_cmd import (
                run_deployment_assess,
                run_deployment_deploy,
            )
            from semapact.interfaces.outcomes import exit_code_from_outcome

            if args.deployment_command == "assess":
                result = run_deployment_assess(args)
            elif args.deployment_command == "deploy":
                result = run_deployment_deploy(args)
            else:
                parser.error(f"Unknown deployment command: {args.deployment_command}")
            print(result.output)
            return int(exit_code_from_outcome(result.outcome))

        if args.command == "release":
            from semapact.interfaces.commands.release_cmd import (
                run_release_approve,
                run_release_assess,
                run_release_classify,
                run_release_classify_repo,
                run_release_finalize,
                run_release_plan,
            )
            if args.release_command == "assess":
                payload = run_release_assess(args)
                print(json.dumps(payload, indent=2, sort_keys=True))
                return 0
            if args.release_command == "approve":
                payload = run_release_approve(args)
                print(json.dumps(payload, indent=2, sort_keys=True))
                return 0
            if args.release_command == "finalize":
                payload = run_release_finalize(args)
                print(json.dumps(payload, indent=2, sort_keys=True))
                return 0
            if args.release_command == "classify":
                payload = run_release_classify(args)
                print(json.dumps(payload, indent=2, sort_keys=True))
                return 0
            if args.release_command == "plan":
                payload = run_release_plan(args)
                print(json.dumps(payload, indent=2, sort_keys=True))
                return 0
            if args.release_command == "classify-repo":
                payload = run_release_classify_repo(args)
                print(json.dumps(payload, indent=2, sort_keys=True))
                return 0

        from semapact.interfaces.outcomes import CliExitCode
        parser.error(f"Unknown command: {args.command}")
        return int(CliExitCode.VALIDATION_FAILED)

    except KeyboardInterrupt:
        return 130
    except SystemExit as exc:
        from semapact.interfaces.outcomes import CliExitCode
        return exc.code if isinstance(exc.code, int) else int(CliExitCode.RUNTIME_ERROR)
    except Exception as exc:
        import logging
        from semapact.exceptions import (
            GovernanceBlockedError,
            GovernanceReviewRequiredError,
            SemaPactError,
        )
        from semapact.interfaces.outcomes import exit_code_from_exception

        if isinstance(exc, (GovernanceBlockedError, GovernanceReviewRequiredError)):
            logging.getLogger("semapact").info("Governance decision: %s", exc)
        elif isinstance(exc, SemaPactError):
            logging.getLogger("semapact").error("Fatal error: %s", exc)
        else:
            logging.getLogger("semapact").error(
                "Fatal error: %s", exc, exc_info=True
            )
        print(f"❌ {exc}", file=__import__("sys").stderr)
        return exit_code_from_exception(exc)


if __name__ == "__main__":
    raise SystemExit(main())