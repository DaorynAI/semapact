import argparse
import json
from pathlib import Path
from typing import Any
from semapact.interfaces.commands.utils import _build_git_config, _get_repo_path

def run_release_classify(args: argparse.Namespace) -> dict[str, Any]:
    from semapact.core.loader import ContractLoader
    from semapact.core.release import suggest_release_version
    from semapact.governance import (
        GovernanceOperation,
        evaluate_governance_decision,
        evaluate_governance_gate,
    )

    loader = ContractLoader(runtime_context=args.runtime_context)
    base_contract = loader.load(args.base)
    candidate_contract = loader.load(args.candidate)

    decision = evaluate_governance_decision(base_contract, candidate_contract)
    evaluate_governance_gate(decision, GovernanceOperation.ANALYZE)

    current_version = str(base_contract.version or "")
    breaking_list = [
        v.model_dump(mode="json")
        for v in decision.policy.violations
        if v.code == "POLICY_BREAKING_CHANGE"
    ]
    reasons_list = [r.message for r in decision.reasons] or ["No contract changes detected"]

    return {
        "contractId": str(base_contract.id or ""),
        "currentVersion": current_version,
        "candidateVersion": str(candidate_contract.version or ""),
        "hasChanges": decision.evidence.has_changes,
        "requiredBump": decision.required_version_bump,
        "suggestedNextVersion": (
            suggest_release_version(current_version, decision.required_version_bump)
            if decision.evidence.has_changes and decision.required_version_bump != "none"
            else current_version
        ),
        "reasons": reasons_list,
        "breakingChanges": breaking_list,
        "governanceDecision": decision.model_dump(mode="json"),
    }

def run_release_prepare(args: argparse.Namespace) -> dict[str, Any]:
    from semapact.core.loader import ContractLoader
    from semapact.core.release import prepare_release_candidate
    from semapact.governance import (
        GovernanceOperation,
        enforce_governance_gate,
        evaluate_governance_decision,
    )
    from semapact.utils.schema_utils import contract_to_dict
    from semapact.utils.yaml_utils import dump_yaml
    from dataclasses import asdict

    loader = ContractLoader(runtime_context=args.runtime_context)
    base_contract = loader.load(args.base)
    candidate_contract = loader.load(args.candidate)

    decision = evaluate_governance_decision(base_contract, candidate_contract)
    enforce_governance_gate(decision, GovernanceOperation.PROPOSE)

    result = prepare_release_candidate(
        base_contract, candidate_contract, args.release_tag
    )
    output_path = dump_yaml(contract_to_dict(result.contract), args.output)
    return {
        "contractId": str(result.contract.id or ""),
        "currentVersion": result.current_version,
        "targetVersion": result.target_version,
        "requiredBump": result.required_bump,
        "actualBump": result.actual_bump,
        "releaseTag": result.release_tag,
        "reasons": result.reasons,
        "breakingChanges": [asdict(change) for change in result.breaking_changes],
        "output": str(output_path),
        "governanceDecision": decision.model_dump(mode="json"),
    }

def run_release_classify_repo(args: argparse.Namespace) -> dict[str, Any]:
    from semapact.devops.release_workflow import (
        classify_contracts_in_repo,
        repository_change_to_dict,
    )

    results = classify_contracts_in_repo(
        base_root=args.base_root,
        candidate_root=args.candidate_root,
    )
    return {
        "contracts": [repository_change_to_dict(item) for item in results],
    }

def run_release_build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    from semapact.devops.release_workflow import (
        build_batch_release_manifest,
        batch_task_to_dict,
        batch_manifest_build_to_dict,
    )

    build = build_batch_release_manifest(
        base_root=args.base_root,
        candidate_root=args.candidate_root,
        target_branch=args.target_branch,
        source_branch_prefix=args.source_branch_prefix,
    )
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            [batch_task_to_dict(item) for item in build.tasks], indent=2, sort_keys=True
        ),
        encoding="utf-8",
    )
    payload = batch_manifest_build_to_dict(build)
    payload["output"] = str(output_path)
    return payload

def run_release_create_pr(args: argparse.Namespace) -> dict[str, Any]:
    from semapact.core.loader import ContractLoader
    from semapact.devops.release_workflow import create_release_pull_request

    loader = ContractLoader(runtime_context=args.runtime_context)
    base_contract = loader.load(args.base)
    candidate_contract = loader.load(args.candidate)

    config = _build_git_config(args)
    payload = create_release_pull_request(
        config=config,
        repo_path=_get_repo_path(args),
        contract_repo_path=args.contract_path,
        base_contract=base_contract,
        candidate_contract=candidate_contract,
        release_tag=args.release_tag,
        source_branch=args.source_branch,
        target_branch=args.target_branch,
        title=args.title,
        description=args.description,
        commit_message=args.commit_message,
        push=args.push,
    )
    return payload

def run_release_create_prs(args: argparse.Namespace) -> dict[str, Any]:
    from semapact.devops.release_workflow import (
        load_batch_release_tasks,
        create_release_pull_requests_from_manifest,
        batch_task_to_dict,
    )

    config = _build_git_config(args)
    tasks = load_batch_release_tasks(args.manifest)
    payload = create_release_pull_requests_from_manifest(
        config=config,
        repo_path=_get_repo_path(args),
        tasks=tasks,
        push=args.push,
    )
    return {
        "tasks": [batch_task_to_dict(item) for item in tasks],
        "results": payload,
    }
