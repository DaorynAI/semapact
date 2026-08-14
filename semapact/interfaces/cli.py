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

    release_parser = subparsers.add_parser(
        "release", help="Per-contract release workflow helpers"
    )
    release_subparsers = release_parser.add_subparsers(
        dest="release_command", required=True
    )

    release_classify_parser = release_subparsers.add_parser(
        "classify",
        help="Classify the required version bump for one contract change set",
    )
    release_classify_parser.add_argument("--base", required=True)
    release_classify_parser.add_argument("--candidate", required=True)
    release_classify_parser.add_argument("--runtime-context", default="auto")
    _add_effective_date_argument(release_classify_parser)

    release_classify_repo_parser = release_subparsers.add_parser(
        "classify-repo",
        help="Classify per-contract required bumps across two contract roots",
    )
    release_classify_repo_parser.add_argument("--base-root", required=True)
    release_classify_repo_parser.add_argument("--candidate-root", required=True)
    _add_effective_date_argument(release_classify_repo_parser)

    release_build_manifest_parser = release_subparsers.add_parser(
        "build-manifest",
        help="Build an editable per-contract release manifest from two contract roots",
    )
    release_build_manifest_parser.add_argument("--base-root", required=True)
    release_build_manifest_parser.add_argument("--candidate-root", required=True)
    release_build_manifest_parser.add_argument("--output", required=True)
    release_build_manifest_parser.add_argument("--target-branch", default="release")
    release_build_manifest_parser.add_argument(
        "--source-branch-prefix", default="release/"
    )
    _add_effective_date_argument(release_build_manifest_parser)

    release_prepare_parser = release_subparsers.add_parser(
        "prepare",
        help="Prepare one promoted contract candidate using an explicit release tag",
    )
    release_prepare_parser.add_argument("--base", required=True)
    release_prepare_parser.add_argument("--candidate", required=True)
    release_prepare_parser.add_argument("--release-tag", required=True)
    release_prepare_parser.add_argument("--output", required=True)
    release_prepare_parser.add_argument("--runtime-context", default="auto")
    _add_effective_date_argument(release_prepare_parser)

    release_pr_parser = release_subparsers.add_parser(
        "create-pr",
        help="Prepare one promoted contract candidate and open a release PR",
    )
    release_pr_parser.add_argument("--base", required=True)
    release_pr_parser.add_argument("--candidate", required=True)
    release_pr_parser.add_argument("--release-tag", required=True)
    release_pr_parser.add_argument("--repo-path", help="Local repository path")
    release_pr_parser.add_argument("--contract-path", required=True)
    release_pr_parser.add_argument("--source-branch", required=True)
    release_pr_parser.add_argument("--target-branch", required=True)
    release_pr_parser.add_argument(
        "--git-provider",
        choices=["azure", "github"],
    )
    release_pr_parser.add_argument("--organization")
    release_pr_parser.add_argument("--github-owner")
    release_pr_parser.add_argument("--github-repo")
    release_pr_parser.add_argument("--github-token")
    release_pr_parser.add_argument("--project")
    release_pr_parser.add_argument("--repository-id")
    release_pr_parser.add_argument("--pat-token")
    release_pr_parser.add_argument("--title")
    release_pr_parser.add_argument("--description")
    release_pr_parser.add_argument("--commit-message")
    release_pr_parser.add_argument("--push", action="store_true")
    release_pr_parser.add_argument("--runtime-context", default="auto")
    _add_effective_date_argument(release_pr_parser)

    release_prs_parser = release_subparsers.add_parser(
        "create-prs",
        help="Run explicit per-contract release PR automation from a batch manifest",
    )
    release_prs_parser.add_argument("--manifest", required=True)
    release_prs_parser.add_argument("--repo-path", help="Local repository path")
    release_prs_parser.add_argument(
        "--git-provider",
        choices=["azure", "github"],
    )
    release_prs_parser.add_argument("--organization")
    release_prs_parser.add_argument("--github-owner")
    release_prs_parser.add_argument("--github-repo")
    release_prs_parser.add_argument("--github-token")
    release_prs_parser.add_argument("--project")
    release_prs_parser.add_argument("--repository-id")
    release_prs_parser.add_argument("--pat-token")
    release_prs_parser.add_argument("--push", action="store_true")

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
                return 1
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

        if args.command == "release":
            from semapact.interfaces.commands.release_cmd import (
                run_release_classify, run_release_classify_repo, run_release_build_manifest,
                run_release_prepare, run_release_create_pr, run_release_create_prs
            )
            if args.release_command == "classify":
                payload = run_release_classify(args)
                print(json.dumps(payload, indent=2, sort_keys=True))
                return 0
            if args.release_command == "classify-repo":
                payload = run_release_classify_repo(args)
                print(json.dumps(payload, indent=2, sort_keys=True))
                return 0
            if args.release_command == "build-manifest":
                payload = run_release_build_manifest(args)
                print(json.dumps(payload, indent=2, sort_keys=True))
                return 0
            if args.release_command == "prepare":
                payload = run_release_prepare(args)
                print(json.dumps(payload, indent=2, sort_keys=True))
                return 0
            if args.release_command == "create-pr":
                payload = run_release_create_pr(args)
                print(json.dumps(payload, indent=2, sort_keys=True))
                return 0
            if args.release_command == "create-prs":
                payload = run_release_create_prs(args)
                print(json.dumps(payload, indent=2, sort_keys=True))
                return 0

        parser.error(f"Unknown command: {args.command}")
        return 2

    except KeyboardInterrupt:
        return 130
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:
        from semapact.exceptions import SemaPactError
        import logging

        if isinstance(exc, SemaPactError):
            logging.getLogger("semapact").error("Fatal error: %s", exc)
        else:
            logging.getLogger("semapact").error(
                "Fatal error: %s", exc, exc_info=True
            )
        print(f"❌ {exc}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())